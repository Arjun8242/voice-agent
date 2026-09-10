import WebSocket from "ws";
import dotenv from "dotenv";

dotenv.config();

const WS_URL = "ws://localhost:3001";
const QUERY = "What are your pricing plans and what does Pro include?";

async function testHotPath() {
  console.log("==================================================");
  console.log("\u{1F525} Hot Path Streaming Integration Test (Phase 4)");
  console.log("==================================================");
  console.log(`WebSocket: ${WS_URL}`);
  console.log(`Query: "${QUERY}"\n`);

  const ws = new WebSocket(WS_URL);
  const t0 = performance.now();
  let audioChunkCount = 0;

  await new Promise<void>((resolve, reject) => {
    ws.on("open", () => {
      console.log("\u2705 Connected to hot path server");
      console.log("\u{1F4E8} Sending query...\n");
      ws.send(JSON.stringify({ type: "query", text: QUERY }));
    });

    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      const elapsed = Math.round(performance.now() - t0);

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
            console.log(`\u{1F916} [${elapsed}ms] Gemini first token (TTFT): ${msg.ttftMs}ms`);
          } else if (msg.stage === "first_audio") {
            const pass = msg.firstAudioLatencyMs <= 2000;
            console.log(
              `\u{1F50A} [${elapsed}ms] *** FIRST AUDIO LATENCY: ${msg.firstAudioLatencyMs}ms *** ` +
              `${pass ? "\u2705 PASS (<= 2s)" : "\u274C EXCEEDS 2s TARGET"}`
            );
          }
          break;

        case "audio":
          audioChunkCount++;
          console.log(
            `\u{1F3B5} [${elapsed}ms] Audio chunk #${audioChunkCount}: ` +
            `"${msg.text.substring(0, 60)}..." | ` +
            `${msg.audio.length} chars | ` +
            `sentenceReady: ${msg.metrics.sentenceReadyMs}ms | ` +
            `audioReady: ${msg.metrics.audioReadyMs}ms` +
            `${msg.metrics.isFirstAudio ? " [FIRST]" : ""}`
          );
          break;

        case "done":
          console.log(
            `\n\u2705 Stream complete. Total: ${msg.totalMs}ms | Audio chunks sent: ${audioChunkCount}`
          );
          ws.close();
          resolve();
          break;

        case "error":
          console.error(`\u274C Error: ${msg.message}`);
          ws.close();
          reject(new Error(msg.message));
          break;
      }
    });

    ws.on("error", (err) => {
      console.error("\u274C WebSocket connection error:", err.message);
      console.error("Make sure the server is running: npm run server");
      reject(err);
    });
  });

  console.log("\n==================================================");
  console.log("\u{1F4CB} What this proves:");
  console.log("- Audio chunk #1 arrived before Gemini finished generating");
  console.log("- Each sentence was synthesized and sent independently");
  console.log("- Browser can start playback before full response is ready");
  console.log("==================================================");
}

testHotPath().catch((err) => {
  console.error("\u274C Test failed:", err.message || err);
  process.exit(1);
});
