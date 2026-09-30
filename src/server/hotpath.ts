import { WebSocketServer, WebSocket } from "ws";
import { retrieveLocal as retrieve, initLocalRetriever } from "../services/rag/local_retriever.js";
import { generateAnswerStream, FALLBACK_ANSWER, Turn } from "../services/rag/llm.js";
import dotenv from "dotenv";
import { appendFile, appendFileSync } from "fs";
dotenv.config();

const PORT = 3001;
const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
const SARVAM_STT_URL =
  "wss://api.sarvam.ai/speech-to-text-realtime/ws" +
  "?language_code=en-IN" +
  "&model=saaras:v3-realtime" +
  "&stream_type=balanced";

// Max number of audio messages to queue while STT socket is connecting
const STT_QUEUE_MAX = 50;

// ---------------------------------------------------------------------------
// Session state per WebSocket connection
// ---------------------------------------------------------------------------

interface Session {
  sttWs: WebSocket | null;
  sttQueue: string[];         // base64 audio_input JSON strings buffered while STT connects
  pingTimer: ReturnType<typeof setInterval> | null;
  turnId: number;             // monotonically increasing; supersedes old turns on barge-in
  turnAbort: AbortController; // aborted when a new turn supersedes the current one
  pipelineRunning: boolean;
  history: Turn[];
}

function newSession(): Session {
  return {
    sttWs: null,
    sttQueue: [],
    pingTimer: null,
    turnId: 0,
    turnAbort: new AbortController(),
    pipelineRunning: false,
    history: [],
  };
}

// ---------------------------------------------------------------------------
// Sentence / clause boundary detection
// ---------------------------------------------------------------------------

function extractNextSentence(buffer: string) {
  const index = buffer.search(/[.!?]/);
  if (index === -1) return null;
  return {
    sentence: buffer.slice(0, index + 1).trim(),
    remaining: buffer.slice(index + 1).trim(),
  };
}

// ---------------------------------------------------------------------------
// TTS: stream one sentence to Sarvam, forward chunks to browser
// ---------------------------------------------------------------------------

async function streamTTSChunks(
  ws: WebSocket,
  send: (type: string | Buffer, payload?: object) => void,
  sentenceId: number,
  text: string,
  elapsed: () => number,
  firstAudioRef: { sentMs: number | null },
  signal: AbortSignal
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
      signal,
    });

    const ttsHttpResponseMs = elapsed();
    send("metric", {
      stage: "tts_http_response",
      sentenceId,
      ttsHttpResponseMs,
      ttsConnectionLatencyMs: ttsHttpResponseMs - ttsConnectionStartMs,
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
    const idBuf = Buffer.allocUnsafe(4);
    idBuf.writeUInt32LE(sentenceId, 0);

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value || value.byteLength === 0) continue;
      if (ws.readyState !== WebSocket.OPEN) { reader.cancel(); return; }
      if (signal.aborted) { reader.cancel(); return; }

      const now = elapsed();
      if (ttsFirstAudioMs === null) {
        ttsFirstAudioMs = now;
        send("metric", {
          stage: "tts_first_audio_chunk",
          sentenceId,
          ttsFirstAudioMs,
          ttsDecodeLatencyMs: ttsFirstAudioMs - ttsHttpResponseMs,
        });
      }

      send(Buffer.concat([idBuf, Buffer.from(value)]));
      chunkCount++;

      if (firstAudioRef.sentMs === null) {
        firstAudioRef.sentMs = now;
        isFirstForStream = true;
        console.log(`[hotpath] 🎯 FIRST AUDIO → BROWSER: ${now}ms`);
        send("metric", { stage: "browser_first_audio", firstAudioMs: now });
      }
    }
  } catch (err: any) {
    if (err.name !== "AbortError") {
      console.error("[TTS] Fetch error:", err.message);
      send("tts_error", { sentenceId, message: err.message });
    }
    return;
  }

  send("tts_end", {
    sentenceId,
    chunkCount,
    ttsFirstAudioMs,
    isFirst: isFirstForStream,
    firstAudioLatencyMs: isFirstForStream ? firstAudioRef.sentMs : null,
    trueStreaming: ttsFirstAudioMs !== null && chunkCount > 1,
  });
}

// ---------------------------------------------------------------------------
// Per-connection query handler — guarded by turnId throughout
// ---------------------------------------------------------------------------

async function handleQuery(
  ws: WebSocket,
  send: (type: string | Buffer, payload?: object) => void,
  query: string,
  session: Session,
  turn: number,
  signal: AbortSignal
): Promise<void> {
  const time_initial = performance.now();
  const elapsed = () => Math.round(performance.now() - time_initial);

  const ts: Record<string, number> = {};
  const mark = (label: string) => { ts[label] = elapsed(); };

  // ── Step 1: RAG ──────────────────────────────────────────────────────────
  mark("embeddingStart");
  let ragResult: Awaited<ReturnType<typeof retrieve>>;
  try {
    ragResult = await retrieve(query, 3);
  } catch (err: any) {
    send("error", { message: "RAG failed: " + err.message });
    return;
  }

  // Superseded while waiting for RAG?
  if (turn !== session.turnId) return;

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
    embeddingStartMs: ts["embeddingStart"],
    embeddingEndMs: ts["embeddingEnd"],
    qdrantStartMs: ts["qdrantStart"],
    qdrantEndMs: ts["qdrantEnd"],
    ragEndMs: ts["ragEnd"],
  });

  // ── Step 2: Streaming Gemini LLM ─────────────────────────────────────────
  let sentenceBuffer = "";
  let geminiFirstTokenMs: number | null = null;
  let sentenceCounter = 0;
  const firstAudioRef = { sentMs: null as number | null };
  const ttsPromises: Promise<void>[] = [];
  let assistantResponse = "";
  const sentenceReadyTimes: number[] = [];

  const flushSentence = (sentence: string) => {
    if (turn !== session.turnId) return; // superseded
    const sentenceId = sentenceCounter++;
    const sentenceReadyMs = elapsed();
    sentenceReadyTimes.push(sentenceReadyMs);
    console.log(`[hotpath] Sentence #${sentenceId} ready at ${sentenceReadyMs}ms: "${sentence.slice(0, 60)}…"`);
    send("metric", { stage: "sentence_ready", sentenceId, sentenceReadyMs });
    if (ws.readyState === WebSocket.OPEN) {
      const p = streamTTSChunks(ws, send, sentenceId, sentence, elapsed, firstAudioRef, signal).catch((err) => {
        if (err.name !== "AbortError") console.error(`[hotpath] TTS error sentence #${sentenceId}:`, err.message);
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
        if (signal.aborted || turn !== session.turnId) break;

        const tokenText = chunk.text();
        if (!tokenText) continue;

        if (geminiFirstTokenMs === null) {
          geminiFirstTokenMs = elapsed();
          mark("llmFirstToken");
          send("metric", {
            stage: "gemini_first_token",
            ttftMs: geminiFirstTokenMs,
            llmTTFT: geminiFirstTokenMs - ts["llmStart"],
          });
        }

        assistantResponse += tokenText;
        send("assistant_text", { text: tokenText });

        sentenceBuffer += tokenText;
        let extracted = extractNextSentence(sentenceBuffer);
        while (extracted) {
          flushSentence(extracted.sentence);
          sentenceBuffer = extracted.remaining;
          extracted = extractNextSentence(sentenceBuffer);
        }
      }

      mark("llmEnd");

      // Flush any trailing text that didn't end with punctuation
      if (sentenceBuffer.trim() && turn === session.turnId) {
        flushSentence(sentenceBuffer.trim());
      }
    }

    await Promise.all(ttsPromises);

    if (turn !== session.turnId) return; // superseded after TTS

    mark("ttsEnd");
    send("done", { totalMs: elapsed() });

    send("metrics_summary", {
      embeddingLatencyMs: ragResult.embedLatencyMs,
      qdrantLatencyMs: ragResult.qdrantLatencyMs,
      ragTotalMs: ragResult.latencyMs,
      llmStartMs: ts["llmStart"] ?? null,
      llmFirstTokenMs: ts["llmFirstToken"] ?? null,
      llmEndMs: ts["llmEnd"] ?? null,
      llmTTFT: ts["llmFirstToken"] != null && ts["llmStart"] != null
        ? ts["llmFirstToken"] - ts["llmStart"]
        : null,
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
    if (err.name !== "AbortError") {
      console.error("[hotpath] Streaming error:", err.message);
      send("error", { message: "LLM streaming error: " + err.message });
    }
  } finally {
    if (turn === session.turnId) {
      session.pipelineRunning = false;
    }
  }
}

// ---------------------------------------------------------------------------
// STT WebSocket — open per session, queue early audio, handle all Sarvam events
// ---------------------------------------------------------------------------

function sendAudioToSTT(sttWs: WebSocket, audioBase64: string): void {
  sttWs.send(JSON.stringify({ event: "audio_input", audio: audioBase64 }));
}

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

    // Flush any audio that arrived before the socket was ready
    for (const msg of session.sttQueue) {
      sttWs.send(msg);
    }
    session.sttQueue = [];

    // Keepalive ping every 5 s (Sarvam idle timeout is ~30 s)
    session.pingTimer = setInterval(() => {
      if (sttWs.readyState === WebSocket.OPEN) {
        sttWs.ping();
      }
    }, 5000);
  });

  sttWs.on("message", (data: Buffer) => {
    let event: any;
    try { event = JSON.parse(data.toString()); } catch { return; }

    console.log("[STT] Event:", JSON.stringify(event));

    if (event.event === "session.begin") {
      console.log("[STT] Session begun, request_id:", event.request_id);
      return;
    }

    // VAD speech start — barge-in: supersede the current turn
    if (event.event === "vad.speech_start" || event.type === "speech_start") {
      if (session.pipelineRunning) {
        console.log("[STT] Barge-in detected — superseding current turn");
        session.turnId++;
        session.turnAbort.abort();
        session.turnAbort = new AbortController();
        session.pipelineRunning = false;
        send("interrupted");
      }
      return;
    }

    // VAD speech end — informational only; Sarvam will emit is_final transcript
    if (event.event === "vad.speech_end" || event.type === "speech_end") {
      return;
    }

    // Transcript events: handle both { event: "transcript", ... } and { event: "transcript.partial" / "transcript.final" }
    const isTranscriptEvent =
      event.event === "transcript" ||
      event.event === "transcript.partial" ||
      event.event === "transcript.final";

    if (isTranscriptEvent) {
      const text: string = event.transcript ?? event.text ?? "";
      const isFinal: boolean = Boolean(
        event.is_final || event.event === "transcript.final"
      );

      if (!text.trim()) return;

      if (isFinal) {
        console.log(`[STT] Final: "${text}"`);
        send("transcript_final", { text });

        // Supersede any running turn and start the new one
        session.turnId++;
        session.turnAbort.abort();
        session.turnAbort = new AbortController();
        session.pipelineRunning = true;

        const turn = session.turnId;
        const signal = session.turnAbort.signal;
        handleQuery(ws, send, text, session, turn, signal).catch(console.error);
      } else {
        console.log(`[STT] Partial: "${text}"`);
        send("transcript_partial", { text });
      }
    }
  });

  sttWs.on("error", (err) => {
    console.error("[STT] Error:", err.message);
    send("error", { message: "STT error: " + err.message });
    clearInterval(session.pingTimer ?? undefined);
    session.pingTimer = null;
  });

  sttWs.on("close", (code, reason) => {
    console.log(`[STT] Disconnected. code=${code}, reason=${reason.toString()}`);
    clearInterval(session.pingTimer ?? undefined);
    session.pingTimer = null;
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
    // Binary = raw PCM from AudioWorklet → encode and relay to Sarvam STT
    if (isBinary) {
      appendFileSync('debug-live.pcm', raw);
      const audioBase64 = raw.toString("base64");
      const audioMsg = JSON.stringify({ event: "audio_input", audio: audioBase64 });

      if (!session.sttWs) {
        openSTT(ws, send, session);
      }

      if (session.sttWs?.readyState === WebSocket.OPEN) {
        session.sttWs.send(audioMsg);
      } else {
        // Queue while STT socket is still connecting (bounded)
        if (session.sttQueue.length < STT_QUEUE_MAX) {
          session.sttQueue.push(audioMsg);
        }
      }
      return;
    }

    // JSON = legacy text query (for test-hotpath.ts compatibility)
    let msg: any;
    try { msg = JSON.parse(raw.toString()); } catch { return; }

    if (msg.type === "query" && typeof msg.text === "string" && msg.text.trim()) {
      session.turnId++;
      session.turnAbort.abort();
      session.turnAbort = new AbortController();
      session.pipelineRunning = true;
      const turn = session.turnId;
      const signal = session.turnAbort.signal;
      handleQuery(ws, send, msg.text.trim(), session, turn, signal).catch(console.error);
    }
  });

  ws.on("close", () => {
    clearInterval(session.pingTimer ?? undefined);
    session.sttWs?.close();
    session.turnAbort.abort();
    console.log("[hotpath] Client disconnected");
  });

  ws.on("error", (err) => console.error("[hotpath] WS error:", err.message));
});

console.log(`🚀 Voice RAG Hot Path WebSocket server running on ws://localhost:${PORT}`);