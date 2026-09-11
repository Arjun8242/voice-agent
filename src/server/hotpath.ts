import { WebSocketServer, WebSocket } from "ws";
import { GoogleGenerativeAI } from "@google/generative-ai";
import { retrieve } from "../services/rag/retriever.js";
import dotenv from "dotenv";

dotenv.config();

const PORT = 3001;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";
const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
const SARVAM_STT_URL = "wss://api.sarvam.ai/v1/speech-to-text";
const GEMINI_MODEL = "gemini-3.5-flash-lite";

if (!GEMINI_API_KEY) throw new Error("GEMINI_API_KEY not set in .env");
if (!SARVAM_API_KEY) throw new Error("SARVAM_API_KEY not set in .env");

const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
const model = genAI.getGenerativeModel({
  model: GEMINI_MODEL,
  generationConfig: { maxOutputTokens: 150, temperature: 0.3 },
});

// ---------------------------------------------------------------------------
// Session state per WebSocket connection
// ---------------------------------------------------------------------------

interface Turn {
  role: "user" | "assistant";
  text: string;
}

interface Session {
  sttWs: WebSocket | null;
  partialText: string;
  debounceTimer: ReturnType<typeof setTimeout> | null;
  pipelineRunning: boolean;
  history: Turn[]; // last 2 turns max
}

function newSession(): Session {
  return { sttWs: null, partialText: "", debounceTimer: null, pipelineRunning: false, history: [] };
}

// ---------------------------------------------------------------------------
// Sentence / clause boundary detection
// ---------------------------------------------------------------------------

function extractNextSentence(buffer: string) {
  const index = buffer.search(/[.!?]/);

  if (index === -1) {
    return null;
  }

  const sentence = buffer.slice(0, index + 1).trim();
  const remaining = buffer.slice(index + 1).trim();

  return {
    sentence,
    remaining,
  };
}

// Ek sentence ko Sarvam TTS API ko bhejta hai → audio ko stream me receive karta hai → har audio chunk WebSocket se frontend ko bhejta hai → latency/statistics track karta hai.

async function streamTTSChunks(
  ws: WebSocket,
  send: (type: string | Buffer, payload?: object) => void,
  sentenceId: number,
  text: string,
  elapsed: () => number,
  firstAudioRef: { sentMs: number | null }
): Promise<void> {
  send("tts_start", { sentenceId, text: text.slice(0, 80) });

  let ttsFirstAudioMs: number | null = null;
  let chunkCount = 0;
  let isFirstForStream = false;

  try {
    const res = await fetch("https://api.sarvam.ai/text-to-speech/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY },
      body: JSON.stringify({
        text,
        language_code: "en-IN",
        model: "bulbul:v3",
        speaker: "shubh",
        output_audio_codec: "mp3",
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`[TTS] Error ${res.status}:`, errText);
      send("tts_error", { sentenceId, message: errText.slice(0, 200) });
      return;
    }
    if (!res.body) {
      send("tts_error", { sentenceId, message: "Streaming not supported" });
      return;
    }

    const reader = res.body.getReader();
    //sentence id ko 4 bytes meh convert, ye har audio packet ke start mein attach hota hai
    const idBuf = Buffer.allocUnsafe(4);
    idBuf.writeUInt32LE(sentenceId, 0);

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value || value.byteLength === 0) continue;
      if (ws.readyState !== WebSocket.OPEN) { reader.cancel(); return; }

      const now = elapsed();
      if (ttsFirstAudioMs === null) ttsFirstAudioMs = now;

      //send buffer -> [sentence_id, audio_chunk1, audio_chunk2, ...]
      send(Buffer.concat([idBuf, Buffer.from(value)]));
      chunkCount++;

      //pehle audio packet ka timestamp
      if (firstAudioRef.sentMs === null) {
        firstAudioRef.sentMs = now;
        isFirstForStream = true;
        console.log(`[hotpath] 🎯 FIRST AUDIO LATENCY: ${now}ms`);
      }
    }
  } catch (err: any) {
    console.error("[TTS] Fetch error:", err.message);
    send("tts_error", { sentenceId, message: err.message });
    return;
  }

  send("tts_end", {
    sentenceId, chunkCount, ttsFirstAudioMs,
    isFirst: isFirstForStream,
    firstAudioLatencyMs: isFirstForStream ? firstAudioRef.sentMs : null,
    trueStreaming: ttsFirstAudioMs !== null && chunkCount > 1,
  });
}

// ---------------------------------------------------------------------------
// Phase 7: Parallel RAG + prompt with conversation history
// ---------------------------------------------------------------------------

function buildPrompt(query: string, context: string, history: Turn[]): string {
  const systemPrompt = "You are a concise voice assistant for Acme Voice AI. Answer in 1 to 2 short sentences. No markdown, no bullet points.";

  //conversation history
  let historyBlock = "";
  if (history.length > 0) {
    historyBlock = "\n\nPrevious conversation:\n" +
      history.map(t => `${t.role === "user" ? "User" : "Assistant"}: ${t.text}`).join("\n");
  }

  return (
    `${systemPrompt}${historyBlock}\n\n` +
    `Relevant Context:\n${context || "No specific context found."}\n\n` +
    `User Question: ${query}`
  );
}

// ---------------------------------------------------------------------------
// Per-connection query handler (called from STT partial trigger)
// ---------------------------------------------------------------------------

async function handleQuery(
  ws: WebSocket,
  send: (type: string | Buffer, payload?: object) => void,
  query: string,
  session: Session
): Promise<void> {
  const time_initial = performance.now();
  const elapsed = () => Math.round(performance.now() - time_initial);

  // Phase 7: Start RAG retrieval and prompt scaffold in parallel
  // (prompt scaffold is sync; both start at the same time)
  let context = "";
  try {
    const ragResult = await retrieve(query, 3);
    context = ragResult.combinedContext;

    send("metric", {
      stage: "rag_complete",
      ragLatencyMs: ragResult.latencyMs,
      chunksFound: ragResult.chunks.length,
      elapsedMs: elapsed(),
    });
  } catch (err: any) {
    send("error", { message: "RAG failed: " + err.message });
    session.pipelineRunning = false;
    return;
  }

  // Merge: inject context + history into prompt
  const fullPrompt = buildPrompt(query, context, session.history);

  let sentenceBuffer = "";
  let geminiFirstTokenMs: number | null = null;
  let sentenceCounter = 0;
  const firstAudioRef = { sentMs: null as number | null };
  const ttsPromises: Promise<void>[] = [];
  let assistantResponse = "";

  //jab ek full sentence ban jaye, usey TTS ko send karo and TTS audio chunks ko frontend ko stream karo
  const flushSentence = (sentence: string) => {
    const sentenceId = sentenceCounter++;
    console.log(`[hotpath] Sentence #${sentenceId} at ${elapsed()}ms: "${sentence.slice(0, 60)}…"`);
    send("metric", { stage: "sentence_ready", sentenceId, sentenceReadyMs: elapsed() });
    if (ws.readyState === WebSocket.OPEN) {
      const p = streamTTSChunks(ws, send, sentenceId, sentence, elapsed, firstAudioRef).catch((err) => {
        console.error(`[hotpath] TTS error sentence #${sentenceId}:`, err.message);
      });
      ttsPromises.push(p);
    }
  };

  try {
    const result = await model.generateContentStream(fullPrompt);

    for await (const chunk of result.stream) {
      if (ws.readyState !== WebSocket.OPEN) break;
      const tokenText = chunk.text();
      if (!tokenText) continue;

      if (geminiFirstTokenMs === null) {
        geminiFirstTokenMs = elapsed();
        send("metric", {
          stage: "gemini_first_token",
          ttftMs: geminiFirstTokenMs,
        });
      }

      assistantResponse += tokenText;
      send("assistant_text", { text: tokenText }); // stream text to UI

      sentenceBuffer += tokenText;
      let extracted = extractNextSentence(sentenceBuffer);
      while (extracted) {
        flushSentence(extracted.sentence);
        sentenceBuffer = extracted.remaining;
        extracted = extractNextSentence(sentenceBuffer);
      }
    }

    if (sentenceBuffer.trim()) flushSentence(sentenceBuffer.trim());

    await Promise.all(ttsPromises);
    send("done", { totalMs: elapsed() });

    // Update conversation history (keep last 2 turns)
    session.history.push({ role: "user", text: query });
    session.history.push({ role: "assistant", text: assistantResponse.trim() });
    if (session.history.length > 4) session.history = session.history.slice(-4); // 2 turns = 4 entries

  } catch (err: any) {
    console.error("[hotpath] Gemini error:", err.message);
    send("error", { message: "Gemini error: " + err.message });
  } finally {
    session.pipelineRunning = false;
  }
}

// ---------------------------------------------------------------------------
// Phase 6: Sarvam STT WebSocket — open per session, relay PCM, handle events
// ---------------------------------------------------------------------------

function openSTT(
  ws: WebSocket,
  send: (type: string | Buffer, payload?: object) => void,
  session: Session
): void {
  const sttWs = new WebSocket(SARVAM_STT_URL, {
    headers: { "api-subscription-key": SARVAM_API_KEY },
  });

  session.sttWs = sttWs;

  sttWs.on("open", () => {
    console.log("[STT] Connected to Sarvam STT");
    // Send init config
    sttWs.send(JSON.stringify({
      language_code: "en-IN",
      model: "saarika:v2",
      enable_partial_transcripts: true,
    }));
  });

  sttWs.on("message", (data: Buffer) => {
    let event: any;
    try { event = JSON.parse(data.toString()); } catch { return; }

    if (event.type === "transcript" || event.transcript) {
      const text: string = event.transcript ?? event.text ?? "";
      const isFinal: boolean = event.is_final ?? false;

      if (!text.trim()) return;

      if (isFinal) {
        clearTimeout(session.debounceTimer ?? undefined);
        session.debounceTimer = null;
        session.partialText = "";
        send("transcript_final", { text });
        console.log(`[STT] Final: "${text}"`);

        // Trigger pipeline if not already running
        if (!session.pipelineRunning) {
          session.pipelineRunning = true;
          handleQuery(ws, send, text, session).catch(console.error);
        }
      } else {
        session.partialText = text;
        send("transcript_partial", { text });

        // Debounced partial trigger: ≥5 words, stable for 300ms
        if (text.split(" ").length >= 5 && !session.pipelineRunning) {
          clearTimeout(session.debounceTimer ?? undefined);
          session.debounceTimer = setTimeout(() => {
            if (!session.pipelineRunning) {
              console.log(`[STT] Partial trigger: "${text}"`);
              session.pipelineRunning = true;
              handleQuery(ws, send, text, session).catch(console.error);
            }
          }, 300);
        }
      }
    }
  });

  sttWs.on("error", (err) => {
    console.error("[STT] Error:", err.message);
    send("error", { message: "STT error: " + err.message });
  });

  sttWs.on("close", () => {
    console.log("[STT] Disconnected");
    session.sttWs = null;
  });
}

// ---------------------------------------------------------------------------
// WebSocket server
// ---------------------------------------------------------------------------

const wss = new WebSocketServer({ port: PORT });

wss.on("connection", (ws) => {
  console.log("[hotpath] Client connected");

  const session = newSession();

  const send = (type: string | Buffer, payload?: object) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    if (Buffer.isBuffer(type)) {
      ws.send(type);
    } else {
      ws.send(JSON.stringify({ type, ...(payload ?? {}) }));
    }
  };

  ws.on("message", (raw: Buffer, isBinary: boolean) => {
    // Binary = raw PCM from AudioWorklet → relay to Sarvam STT
    if (isBinary) {
      if (!session.sttWs) openSTT(ws, send, session);
      if (session.sttWs?.readyState === WebSocket.OPEN) {
        session.sttWs.send(raw);
      }
      return;
    }

    // JSON = legacy text query (for test-hotpath.ts compatibility)
    let msg: any;
    try { msg = JSON.parse(raw.toString()); } catch { return; }

    if (msg.type === "query" && typeof msg.text === "string" && msg.text.trim()) {
      if (!session.pipelineRunning) {
        session.pipelineRunning = true;
        handleQuery(ws, send, msg.text.trim(), session).catch(console.error);
      }
    }
  });

  ws.on("close", () => {
    clearTimeout(session.debounceTimer ?? undefined);
    session.sttWs?.close();
    console.log("[hotpath] Client disconnected");
  });

  ws.on("error", (err) => console.error("[hotpath] WS error:", err.message));
});

console.log(`🚀 Voice RAG Hot Path WebSocket server running on ws://localhost:${PORT}`);