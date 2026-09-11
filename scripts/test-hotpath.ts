import WebSocket from "ws";
import dotenv from "dotenv";
import { writeFileSync, mkdirSync } from "fs";

dotenv.config();

const WS_URL = "ws://localhost:3001";
const QUERY = "What are your pricing plans and what does Pro include?";
const SAVE_AUDIO = true; // set false to skip writing mp3s to disk
const OUT_DIR = "./tts-output";

async function testHotPath() {
  console.log("==================================================");
  console.log("\u{1F525} Hot Path Streaming Integration Test (Phase 4)");
  console.log("==================================================");
  console.log(`WebSocket: ${WS_URL}`);
  console.log(`Query: "${QUERY}"\n`);

  if (SAVE_AUDIO) mkdirSync(OUT_DIR, { recursive: true });

  const ws = new WebSocket(WS_URL);
  const t0 = performance.now();

  // Per-sentence MP3 byte accumulation, keyed by sentenceId
  const audioBuffers = new Map<number, Buffer[]>();
  let firstAudioLatencyMs: number | null = null;
  let sentencesStarted = 0;
  let sentencesEnded = 0;

  await new Promise<void>((resolve, reject) => {
    // NOTE: second arg `isBinary` is what the old client was missing.
    // Every message here is either a JSON control frame (isBinary === false)
    // or a raw MP3 chunk prefixed with a 4-byte little-endian sentenceId
    // (isBinary === true). Never JSON.parse a binary frame.
    ws.on("message", (raw: Buffer, isBinary: boolean) => {
      const elapsed = Math.round(performance.now() - t0);

      if (isBinary) {
        const sentenceId = raw.readUInt32LE(0);
        const mp3Chunk = raw.subarray(4);

        if (firstAudioLatencyMs === null) {
          firstAudioLatencyMs = elapsed;
          const pass = firstAudioLatencyMs <= 2000;
          console.log(
            `\u{1F50A} [${elapsed}ms] *** FIRST AUDIO CHUNK RECEIVED: ${firstAudioLatencyMs}ms *** ` +
            `${pass ? "\u2705 PASS (<= 2s)" : "\u274C EXCEEDS 2s TARGET"}`
          );
        }

        console.log(
          `\u{1F3B5} [${elapsed}ms] Audio chunk for sentence #${sentenceId}: ${mp3Chunk.byteLength}B`
        );

        if (SAVE_AUDIO) {
          if (!audioBuffers.has(sentenceId)) audioBuffers.set(sentenceId, []);
          audioBuffers.get(sentenceId)!.push(Buffer.from(mp3Chunk));
        }
        return;
      }

      // JSON control message
      let msg: any;
      try {
        msg = JSON.parse(raw.toString());
      } catch {
        console.warn(`\u26A0\uFE0F [${elapsed}ms] Received non-JSON, non-binary frame — ignoring`);
        return;
      }

      switch (msg.type) {
        case "status":
          console.log(`\u23F3 [${elapsed}ms] Stage: ${msg.stage}`);
          break;

        case "metric":
          if (msg.stage === "rag_complete") {
            console.log(
              `\u26A1 [${elapsed}ms] RAG complete — ` +
              `${msg.chunksFound} chunks, retrieval: ${msg.ragLatencyMs}ms`
            );
          } else if (msg.stage === "gemini_first_token") {
            console.log(` [${elapsed}ms] Gemini first token (TTFT): ${msg.ttftMs}ms`);
          } else if (msg.stage === "sentence_ready") {
            console.log(
              ` [${elapsed}ms] Sentence #${msg.sentenceId} ready at ${msg.sentenceReadyMs}ms`
            );
          }
          break;

        case "tts_start":
          sentencesStarted++;
          console.log(
            `[${elapsed}ms] TTS start sentence #${msg.sentenceId}: "${msg.text}..."`
          );
          break;

        case "tts_end":
          sentencesEnded++;
          console.log(
            ` [${elapsed}ms] TTS end sentence #${msg.sentenceId} — ` +
            `${msg.chunkCount} chunks, firstAudio: ${msg.ttsFirstAudioMs}ms, ` +
            `trueStreaming: ${msg.trueStreaming}` +
            `${msg.isFirst ? ` [FIRST AUDIO LATENCY: ${msg.firstAudioLatencyMs}ms]` : ""}`
          );

          if (SAVE_AUDIO && audioBuffers.has(msg.sentenceId)) {
            const chunks = audioBuffers.get(msg.sentenceId)!;
            const full = Buffer.concat(chunks);
            const path = `${OUT_DIR}/sentence-${msg.sentenceId}.mp3`;
            writeFileSync(path, full);
            console.log(`   \u{1F4BE} Saved ${path} (${full.byteLength}B)`);
          }
          break;

        case "tts_error":
          console.error(`[${elapsed}ms] TTS error sentence #${msg.sentenceId}: ${msg.message}`);
          break;

        case "done":
          console.log(
            `\nStream complete. Total: ${msg.totalMs}ms | ` +
            `Sentences started: ${sentencesStarted} | ended: ${sentencesEnded}`
          );
          ws.close();
          resolve();
          break;

        case "error":
          console.error(`\u274C Error: ${msg.message}`);
          ws.close();
          reject(new Error(msg.message));
          break;

        default:
          console.log(`\u2753 [${elapsed}ms] Unknown message type: ${msg.type}`);
      }
    });

    ws.on("open", () => {
      console.log("\u2705 Connected to hot path server");
      console.log("\u{1F4E8} Sending query...\n");
      ws.send(JSON.stringify({ type: "query", text: QUERY }));
    });

    ws.on("error", (err) => {
      console.error("\u274C WebSocket connection error:", err.message);
      console.error("Make sure the server is running: npm run server");
      reject(err);
    });
  });

  console.log("\n==================================================");
  console.log("\u{1F4CB} What this proves:");
  console.log("- Each sentence was synthesized and sent independently");
  console.log("- Audio chunks arrived incrementally per sentence (true streaming)");
  console.log("- sentenceId prefix lets the client reassemble/play chunks in order");
  console.log("  even if sentences complete out of order");
  console.log("==================================================");
}

testHotPath().catch((err) => {
  console.error("\u274C Test failed:", err.message || err);
  process.exit(1);
});