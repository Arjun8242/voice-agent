import { WebSocketServer, WebSocket } from "ws";
import { retrieveLocal as retrieve, initLocalRetriever, prefetchQuery } from "../services/rag/local_retriever.js";
import { generateAnswerStream, FALLBACK_ANSWER, Turn } from "../services/rag/llm.js";
import dotenv from "dotenv";

dotenv.config();

const PORT = 3001;
const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
const SARVAM_STT_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws" +
  "?language_code=en-IN" +
  "&model=saaras:v3-realtime" +
  "&stream_type=fast";



// ---------------------------------------------------------------------------
// Session state per WebSocket connection
// ---------------------------------------------------------------------------

interface Session {
  sttWs: WebSocket | null;
  partialText: string;
  debounceTimer: ReturnType<typeof setTimeout> | null;
  pipelineRunning: boolean;
  history: Turn[];
  audioBytesReceived: number;
  audioChunksReceived: number;
}

function newSession(): Session {
  return { sttWs: null, partialText: "", debounceTimer: null, pipelineRunning: false, history: [], audioBytesReceived: 0, audioChunksReceived: 0 };
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
  const ttsConnectionStartMs = elapsed();
  send("tts_start", { sentenceId, text: text.slice(0, 80), ttsConnectionStartMs });

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
        speaker: "suhani",
        output_audio_codec: "mp3",
      }),
    });

    const ttsHttpResponseMs = elapsed();
    // This measures TTS HTTP connection + server TTFA (time-to-first-audio-byte)
    send("metric", { stage: "tts_http_response", sentenceId, ttsHttpResponseMs, ttsConnectionLatencyMs: ttsHttpResponseMs - ttsConnectionStartMs });

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
      if (ttsFirstAudioMs === null) {
        ttsFirstAudioMs = now;
        send("metric", { stage: "tts_first_audio_chunk", sentenceId, ttsFirstAudioMs, ttsDecodeLatencyMs: ttsFirstAudioMs - ttsHttpResponseMs });
      }

      // [sentenceId(4B)][mp3 chunk] — no buffering, forwarded immediately
      send(Buffer.concat([idBuf, Buffer.from(value)]));
      chunkCount++;

      //pehle audio packet ka timestamp
      if (firstAudioRef.sentMs === null) {
        firstAudioRef.sentMs = now;
        isFirstForStream = true;
        console.log(`[hotpath] 🎯 FIRST AUDIO → BROWSER: ${now}ms`);
        send("metric", { stage: "browser_first_audio", firstAudioMs: now });
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
// Streaming LLM is now delegated to llm.ts (generateAnswerStream)
// which enforces Harbor & Pine grounding rules and voice response style.

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

  // ── Critical-path timestamps ──────────────────────────────────────────────
  const ts: Record<string, number> = {};
  const mark = (label: string) => { ts[label] = elapsed(); };

  // ── Step 1: RAG Retrieval (Gemini embedding → Qdrant) ────────────────────
  mark("embeddingStart");
  let ragResult: Awaited<ReturnType<typeof retrieve>>;
  try {
    ragResult = await retrieve(query, 3);
    mark("ragEnd");
    ts["embeddingEnd"] = ts["embeddingStart"] + ragResult.embedLatencyMs;
    ts["qdrantStart"] = ts["embeddingEnd"];
    ts["qdrantEnd"] = ts["qdrantStart"] + ragResult.qdrantLatencyMs;

    send("metric", {
      stage: "rag_complete",
      ragLatencyMs: ragResult.latencyMs,
      embedLatencyMs: ragResult.embedLatencyMs,
      qdrantLatencyMs: ragResult.qdrantLatencyMs,
      chunksFound: ragResult.chunks.length,
      // Breakdown timestamps (ms since query received)
      embeddingStartMs: ts["embeddingStart"],
      embeddingEndMs: ts["embeddingEnd"],
      qdrantStartMs: ts["qdrantStart"],
      qdrantEndMs: ts["qdrantEnd"],
      ragEndMs: ts["ragEnd"],
    });
  } catch (err: any) {
    send("error", { message: "RAG failed: " + err.message });
    session.pipelineRunning = false;
    return;
  }

  // ── Step 2: Streaming Gemini LLM ─────────────────────────────────────────
  let sentenceBuffer = "";
  let geminiFirstTokenMs: number | null = null;
  let sentenceCounter = 0;
  const firstAudioRef = { sentMs: null as number | null };
  const ttsPromises: Promise<void>[] = [];
  let assistantResponse = "";
  const sentenceReadyTimes: number[] = [];

  // As each sentence boundary is detected, immediately flush to Sarvam TTS stream
  const flushSentence = (sentence: string) => {
    const sentenceId = sentenceCounter++;
    const sentenceReadyMs = elapsed();
    sentenceReadyTimes.push(sentenceReadyMs);
    console.log(`[hotpath] Sentence #${sentenceId} ready at ${sentenceReadyMs}ms: "${sentence.slice(0, 60)}…"`);
    send("metric", { stage: "sentence_ready", sentenceId, sentenceReadyMs });
    if (ws.readyState === WebSocket.OPEN) {
      const p = streamTTSChunks(ws, send, sentenceId, sentence, elapsed, firstAudioRef).catch((err) => {
        console.error(`[hotpath] TTS error sentence #${sentenceId}:`, err.message);
      });
      ttsPromises.push(p);
    }
  };

  try {
    if (ragResult.chunks.length === 0) {
      console.log("[hotpath] No RAG chunks — sending approved fallback.");
      flushSentence(FALLBACK_ANSWER);
    } else {
      mark("llmStart");
      send("metric", { stage: "llm_start", llmStartMs: ts["llmStart"] });

      const streamResult = await generateAnswerStream(query, ragResult, session.history);

      for await (const chunk of streamResult.stream) {
        if (ws.readyState !== WebSocket.OPEN) break;
        const tokenText = chunk.text();
        if (!tokenText) continue;

        if (geminiFirstTokenMs === null) {
          geminiFirstTokenMs = elapsed();
          mark("llmFirstToken");
          send("metric", { stage: "gemini_first_token", ttftMs: geminiFirstTokenMs, llmTTFT: geminiFirstTokenMs - ts["llmStart"] });
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

      mark("llmEnd");
      if (sentenceBuffer.trim()) flushSentence(sentenceBuffer.trim());
    }

    await Promise.all(ttsPromises);
    mark("ttsEnd");
    send("done", { totalMs: elapsed() });

    // Emit final latency breakdown for analysis
    send("metrics_summary", {
      embeddingLatencyMs: ragResult.embedLatencyMs,
      qdrantLatencyMs: ragResult.qdrantLatencyMs,
      ragTotalMs: ragResult.latencyMs,
      llmStartMs: ts["llmStart"] ?? null,
      llmFirstTokenMs: ts["llmFirstToken"] ?? null,
      llmEndMs: ts["llmEnd"] ?? null,
      llmTTFT: ts["llmFirstToken"] != null && ts["llmStart"] != null ? ts["llmFirstToken"] - ts["llmStart"] : null,
      firstSentenceReadyMs: sentenceReadyTimes[0] ?? null,
      ttsEndMs: ts["ttsEnd"] ?? null,
      browserFirstAudioMs: firstAudioRef.sentMs,
      totalMs: elapsed(),
    });

    if (assistantResponse.trim()) {
      session.history.push({ role: "user", text: query });
      session.history.push({ role: "assistant", text: assistantResponse.trim() });
      if (session.history.length > 4) session.history = session.history.slice(-4);
    }

  } catch (err: any) {
    console.error("[hotpath] Gemini streaming error:", err.message);
    send("error", { message: "LLM streaming error: " + err.message });
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
    console.log("[STT] Connected to Sarvam Realtime STT");
  });

  sttWs.on("message", (data: Buffer) => {
    let event: any;
    try { event = JSON.parse(data.toString()); } catch { return; }

    console.log("[STT] Event:", JSON.stringify(event));

    // Realtime API: session acknowledgement
    if (event.event === "session.begin") {
      console.log("[STT] Session begun, request_id:", event.request_id);
      return;
    }

    // Realtime API: transcript events (transcript / transcript.partial / transcript.final / data)
    if (
      event.event === "transcript" ||
      event.event?.startsWith("transcript") ||
      event.type === "data"
    ) {
      const text: string =
        event.transcript ?? event.text ?? event.data?.transcript ?? "";
      const isFinal: boolean = Boolean(
        event.is_final ||
        event.event === "transcript.final" ||
        event.type === "final"
      );

      if (!text.trim()) return;

      if (isFinal) {
        // Final transcript — cancel any pending debounce and fire pipeline
        clearTimeout(session.debounceTimer ?? undefined);
        session.debounceTimer = null;
        session.partialText = "";
        console.log(`[STT] Final: "${text}"`);
        send("transcript_final", { text });
        if (!session.pipelineRunning) {
          session.pipelineRunning = true;
          handleQuery(ws, send, text, session).catch(console.error);
        }
      } else {
        // Partial transcript — update UI only
        session.partialText = text;
        console.log(`[STT] Partial: "${text}"`);
        send("transcript_partial", { text });
      }
    }
  });

  sttWs.on("error", (err) => {
    console.error("[STT] Error:", err.message);
    send("error", { message: "STT error: " + err.message });
  });

  sttWs.on("close", (code, reason) => {
    console.log(
      `[STT] Disconnected. code=${code}, reason=${reason.toString()}`
    );
    session.sttWs = null;
  });
}

// ---------------------------------------------------------------------------
// WebSocket server
// ---------------------------------------------------------------------------

await initLocalRetriever();
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
      session.audioBytesReceived += raw.length;
      session.audioChunksReceived++;
      if (session.audioChunksReceived % 20 === 0) { // Log every 20 chunks to avoid spam
        console.log(`[Backend] Received ${session.audioChunksReceived} chunks, total bytes: ${session.audioBytesReceived}`);
      }
      if (!session.sttWs) openSTT(ws, send, session);
      if (session.sttWs?.readyState === WebSocket.OPEN) {
        // Realtime API: { event: "audio_input", audio: "<base64>" }
        const audioBase64 = raw.toString("base64");
        session.sttWs.send(JSON.stringify({
          event: "audio_input",
          audio: audioBase64,
        }));
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