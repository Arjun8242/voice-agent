import { WebSocketServer, WebSocket } from "ws";
import { GoogleGenerativeAI } from "@google/generative-ai";
import { retrieve } from "../services/rag/retriever.js";
import dotenv from "dotenv";

dotenv.config();

const PORT = 3001;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";
const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
const GEMINI_MODEL = "gemini-3.5-flash-lite";

if (!GEMINI_API_KEY) throw new Error("GEMINI_API_KEY not set in .env");
if (!SARVAM_API_KEY) throw new Error("SARVAM_API_KEY not set in .env");

const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);

// ---------------------------------------------------------------------------
// Sentence / clause boundary detection
// ---------------------------------------------------------------------------

/**
 * Tries to extract the first complete sentence from the buffer.
 * Returns { sentence, remaining } if a boundary is found, otherwise null.
 * Also flushes on long clauses (>80 chars ending in comma) to avoid stalls.
 */
function extractNextSentence(
  buffer: string
): { sentence: string; remaining: string } | null {

  // Full sentence boundary: . ! ? followed by whitespace or end-of-string
  const sentenceMatch = buffer.match(/^(.*?[.!?])(\s+|$)/s);
  if (sentenceMatch) {
    return {
      sentence: sentenceMatch[1].trim(),
      remaining: buffer.slice(sentenceMatch[0].length),
    };
  }

  // Clause flush: 50+ chars ending at a comma — sends shorter phrases to TTS sooner
  const clauseMatch = buffer.match(/^(.{50,}?,)\s+/s);
  if (clauseMatch) {
    return {
      sentence: clauseMatch[1].trim(),
      remaining: buffer.slice(clauseMatch[0].length),
    };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Sarvam TTS - true per-chunk streaming
// POST /text-to-speech/stream returns raw MP3 binary frames incrementally.
// We forward EACH chunk immediately over WebSocket as a binary frame,
// wrapped in a 4-byte little-endian sentenceId prefix so the client can
// reconstruct ordering across concurrent sentences.
//
// Protocol:
//   → { type: "tts_start",    sentenceId, text, ttsRequestStartMs }  (JSON)
//   → binary frame: [sentenceId u32LE][mp3 bytes]   (one per Sarvam chunk)
//   → { type: "tts_end",      sentenceId, ttsFirstAudioMs,
//                              websocketAudioSentMs, chunkCount,
//                              isFirst, firstAudioLatencyMs }          (JSON)
// ---------------------------------------------------------------------------

async function streamTTSChunks(
  ws: WebSocket,
  sendJson: (type: string | Buffer, payload?: object) => void,
  sentenceId: number,
  text: string,
  elapsed: () => number,
  isFirstRef: { value: boolean }
): Promise<void> {
  const ttsRequestStartMs = elapsed();

  sendJson("tts_start", { sentenceId, text: text.slice(0, 80), ttsRequestStartMs });

  let ttsFirstAudioMs: number | null = null;
  let websocketAudioSentMs = 0;
  let chunkCount = 0;

  try {
    const res = await fetch("https://api.sarvam.ai/text-to-speech/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
      },
      body: JSON.stringify({
        text,
        language_code: "en-IN",
        model: "bulbul:v3",
        speaker: "shubh",
        output_audio_codec: "mp3", // MP3 frames are self-contained; appendable by MSE
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`[TTS-stream] Error ${res.status}:`, errText);
      sendJson("tts_error", { sentenceId, status: res.status, message: errText.slice(0, 200) });
      return;
    }

    if (!res.body) {
      console.error("[TTS-stream] Response body is null — runtime does not support fetch streaming");
      sendJson("tts_error", { sentenceId, message: "Streaming not supported" });
      return;
    }

    const reader = res.body.getReader();

    // Pre-allocate 4-byte sentenceId prefix (little-endian u32)
    const idBuf = Buffer.allocUnsafe(4);
    idBuf.writeUInt32LE(sentenceId, 0);

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value || value.byteLength === 0) continue;

      if (ws.readyState !== WebSocket.OPEN) { reader.cancel(); return; }

      // Timestamp on very first byte arriving from Sarvam
      if (ttsFirstAudioMs === null) {
        ttsFirstAudioMs = elapsed();
        console.log(
          `[TTS-stream] ⚡ sentenceId=${sentenceId} first byte at ${ttsFirstAudioMs}ms ` +
          `(${ttsFirstAudioMs - ttsRequestStartMs}ms after TTS start)`
        );
      }

      // Forward immediately: [4-byte sentenceId][MP3 bytes]
      const frame = Buffer.concat([idBuf, Buffer.from(value)]);
      sendJson(frame);
      chunkCount++;
      websocketAudioSentMs = elapsed();

      console.log(
        `[TTS-stream] sentenceId=${sentenceId} chunk #${chunkCount} ` +
        `${value.byteLength}B sent at ${websocketAudioSentMs}ms`
      );
    }

  } catch (err: any) {
    console.error("[TTS-stream] Fetch error:", err.message);
    sendJson("tts_error", { sentenceId, message: err.message });
    return;
  }

  const isFirst = isFirstRef.value;
  if (isFirst && chunkCount > 0) {
    isFirstRef.value = false;
    console.log(`[hotpath] 🎯 FIRST AUDIO LATENCY (ws.send): ${websocketAudioSentMs}ms  (ttsFirstByte=${ttsFirstAudioMs}ms)`);
  }

  sendJson("tts_end", {
    sentenceId,
    chunkCount,
    ttsRequestStartMs,
    ttsFirstAudioMs,          // first byte from Sarvam — BEFORE synthesis completed
    websocketAudioSentMs,     // last chunk sent to client
    isFirst,
    firstAudioLatencyMs: isFirst ? websocketAudioSentMs : null,
    // Proof: ttsFirstAudioMs < websocketAudioSentMs means we DID stream
    trueStreaming: ttsFirstAudioMs !== null && chunkCount > 1,
  });
}

// ---------------------------------------------------------------------------
// Per-connection query handler
// ---------------------------------------------------------------------------

async function handleQuery(ws: WebSocket, query: string): Promise<void> {
  const t0 = performance.now();

  const elapsed = () => Math.round(performance.now() - t0);

  // Unified send: JSON control messages OR raw binary frames (Buffer)
  const send = (type: string | Buffer, payload?: object) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    if (Buffer.isBuffer(type)) {
      ws.send(type); // binary frame — MP3 chunk with sentenceId prefix
    } else {
      ws.send(JSON.stringify({ type, ...(payload ?? {}) }));
    }
  };

  // Step 1: RAG retrieval (embedding + Qdrant vector search)
  send("status", { stage: "embedding", elapsedMs: elapsed() });

  let context = "";
  let ragLatencyMs = 0;

  try {
    const ragResult = await retrieve(query, 3);
    ragLatencyMs = ragResult.latencyMs;
    context = ragResult.combinedContext;

    send("metric", {
      stage: "rag_complete",
      ragLatencyMs,
      chunksFound: ragResult.chunks.length,
      elapsedMs: elapsed(),
    });
  } catch (err: any) {
    send("error", { message: "RAG retrieval failed: " + err.message });
    return;
  }

  // Step 2: Assemble prompt
  const systemInstruction =
    "You are a concise voice assistant for Acme Voice AI. " +
    "Answer in 1 to 2 short sentences. No markdown, no bullet points.";

  const fullPrompt =
    `${systemInstruction}\n\n` +
    `Relevant Context:\n${context || "No specific context found."}\n\n` +
    `User Question: ${query}`;

  // Step 3: Gemini streaming -> sentence buffer -> TTS per sentence
  const model = genAI.getGenerativeModel({
    model: GEMINI_MODEL,
    generationConfig: { maxOutputTokens: 150, temperature: 0.3 },
  });

  let sentenceBuffer = "";
  let geminiFirstTokenMs: number | null = null;

  // sentenceId counter — used by the client to correlate binary frames with sentences
  let sentenceCounter = 0;
  // shared flag so streamTTSChunks knows when first audio was sent
  const firstAudioRef = { value: true };

  // TTS calls are chained so chunks from sentence N don't interleave with sentence N+1
  let ttsQueue: Promise<void> = Promise.resolve();

  const flushSentence = (sentence: string, _isLast = false) => {
    const sentenceId = sentenceCounter++;
    const tSentenceReady = elapsed();
    console.log(`[hotpath] Sentence #${sentenceId} ready at ${tSentenceReady}ms: "${sentence.slice(0, 60)}…"`);

    send("metric", { stage: "sentence_ready", sentenceId, sentenceReadyMs: tSentenceReady });

    // Chain: wait for previous sentence's chunks to finish before starting next
    ttsQueue = ttsQueue.then(async () => {
      if (ws.readyState !== WebSocket.OPEN) return;
      await streamTTSChunks(ws, send, sentenceId, sentence, elapsed, firstAudioRef);
    });
  };

  try {
    const result = await model.generateContentStream(fullPrompt);

    for await (const chunk of result.stream) {
      if (ws.readyState !== WebSocket.OPEN) break;

      const tokenText = chunk.text();
      if (!tokenText) continue;

      // Record TTFT on first token
      if (geminiFirstTokenMs === null) {
        geminiFirstTokenMs = elapsed();
        send("metric", {
          stage: "gemini_first_token",
          ttftMs: geminiFirstTokenMs,
        });
      }

      sentenceBuffer += tokenText;

      // Drain all complete sentences from the buffer immediately
      let extracted = extractNextSentence(sentenceBuffer);
      while (extracted) {
        flushSentence(extracted.sentence);
        sentenceBuffer = extracted.remaining;
        extracted = extractNextSentence(sentenceBuffer);
      }
    }

    // Flush any remaining partial text after stream ends
    if (sentenceBuffer.trim()) {
      flushSentence(sentenceBuffer.trim(), true);
    }

    // Wait for all TTS synthesis and sends to complete
    await ttsQueue;

    send("done", { totalMs: elapsed() });

  } catch (err: any) {
    console.error("[hotpath] Gemini error:", err.message);
    send("error", { message: "Gemini stream error: " + err.message });
  }
}

// ---------------------------------------------------------------------------
// WebSocket server
// ---------------------------------------------------------------------------

const wss = new WebSocketServer({ port: PORT });

wss.on("connection", (ws) => {
  console.log("[hotpath] Client connected");

  ws.on("message", (raw) => {
    let msg: any;
    try {
      msg = JSON.parse(raw.toString());
    } catch {
      console.warn("[hotpath] Invalid JSON received");
      return;
    }

    if (msg.type === "query" && typeof msg.text === "string" && msg.text.trim()) {
      handleQuery(ws, msg.text.trim()).catch((err) => {
        console.error("[hotpath] Unhandled error in handleQuery:", err);
      });
    }
  });

  ws.on("close", () => console.log("[hotpath] Client disconnected"));

  ws.on("error", (err) => console.error("[hotpath] WS error:", err.message));
});

console.log(`\u{1F680} Voice RAG Hot Path WebSocket server running on ws://localhost:${PORT}`);
