/**
 * test-stt-file.ts
 * Sends a raw PCM file (s16le, 16kHz, mono) to Sarvam Realtime STT
 * and prints every event received. No application files modified.
 *
 * Usage: npx tsx scripts/test-stt-file.ts <path-to-file.pcm>
 */
import { WebSocket } from "ws";
import * as fs from "fs";
import * as path from "path";
import dotenv from "dotenv";

dotenv.config();

const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
const SARVAM_STT_URL =
  "wss://api.sarvam.ai/speech-to-text-realtime/ws" +
  "?language_code=en-IN" +
  "&model=saaras:v3-realtime" +
  "&stream_type=fast";

const CHUNK_SAMPLES = 1600;          // 100 ms @ 16 kHz
const CHUNK_BYTES   = CHUNK_SAMPLES * 2; // 16-bit = 2 bytes/sample
const SEND_INTERVAL_MS = 100;        // send one chunk every 100 ms (real-time pace)

const filePath = process.argv[2];
if (!filePath) {
  console.error("Usage: npx tsx scripts/test-stt-file.ts <file.pcm>");
  process.exit(1);
}

const absPath = path.resolve(filePath);
console.log(`\n[test] Reading: ${absPath}`);
const pcmData = fs.readFileSync(absPath);
console.log(`[test] File size: ${pcmData.byteLength} bytes (${(pcmData.byteLength / 32000).toFixed(2)} s @ 16kHz mono s16le)`);

const ws = new WebSocket(SARVAM_STT_URL, {
  headers: { "api-subscription-key": SARVAM_API_KEY },
});

let finalTranscript = "";
let chunksSent = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let offset = 0;

ws.on("open", () => {
  console.log("[test] Connected to Sarvam Realtime STT. Streaming audio…\n");

  timer = setInterval(() => {
    if (offset >= pcmData.byteLength) {
      if (timer) { clearInterval(timer); timer = null; }
      console.log(`[test] All ${chunksSent} chunks sent. Streaming 1.5 s silence to trigger VAD…`);

      // Send 1.5 s of silence (zero-amplitude PCM) so the VAD silence timer fires
      // and emits transcript.final. Sarvam requires silence_duration_ms=1000.
      let silenceMs = 0;
      const silenceChunk = Buffer.alloc(CHUNK_BYTES, 0).toString("base64");
      const silenceTimer = setInterval(() => {
        ws.send(JSON.stringify({ event: "audio_input", audio: silenceChunk }));
        silenceMs += SEND_INTERVAL_MS;
        if (silenceMs >= 1500) {
          clearInterval(silenceTimer);
          console.log("[test] Silence sent. Waiting up to 5 s for final transcript…");
          setTimeout(() => {
            console.log("\n[test] Timeout reached. Closing connection.");
            ws.close(1000, "done");
          }, 5000);
        }
      }, SEND_INTERVAL_MS);
      return;
    }

    const end = Math.min(offset + CHUNK_BYTES, pcmData.byteLength);
    const chunk = pcmData.slice(offset, end);
    offset = end;

    const audioBase64 = chunk.toString("base64");
    ws.send(JSON.stringify({ event: "audio_input", audio: audioBase64 }));
    chunksSent++;
  }, SEND_INTERVAL_MS);
});

ws.on("message", (data) => {
  let event: any;
  try { event = JSON.parse(data.toString()); } catch { return; }

  console.log("[STT event]", JSON.stringify(event));

  const isTranscript =
    event.event === "transcript" ||
    event.event === "transcript.partial" ||
    event.event === "transcript.final";

  if (isTranscript) {
    const text: string = event.transcript ?? event.text ?? "";
    const isFinal: boolean = Boolean(event.is_final || event.event === "transcript.final");
    if (isFinal && text.trim()) {
      finalTranscript = text;
    }
  }
});

ws.on("close", (code, reason) => {
  console.log(`\n[test] WebSocket closed. code=${code} reason=${reason.toString() || "(none)"}`);
  console.log("─────────────────────────────────────────");
  console.log(`File:              ${path.basename(absPath)}`);
  console.log(`Final transcript:  "${finalTranscript || "(none received)"}"`);
  const expected = "what is the refund status";
  const got = finalTranscript.toLowerCase().replace(/[^a-z ]/g, "").trim();
  const match = got === expected || got.includes("refund") && got.includes("status");
  console.log(`Expected match:    ${match ? "✅ YES" : "❌ NO"}`);
  console.log("─────────────────────────────────────────\n");
});

ws.on("error", (err) => {
  console.error("[test] WebSocket error:", err.message);
});
