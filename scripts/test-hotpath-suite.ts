/**
 * test-hotpath-suite.ts
 *
 * End-to-end streaming RAG test suite via the WebSocket hotpath server.
 * Tests all 6 required Harbor & Pine queries sequentially.
 *
 * Run:
 *   1. Start the server in another terminal: npm run server
 *   2. Run this suite: npx tsx scripts/test-hotpath-suite.ts
 */
import WebSocket from "ws";
import dotenv from "dotenv";

dotenv.config();

const WS_URL = "ws://localhost:3001";
const FIRST_AUDIO_TARGET_MS = 2000; // advisory target

interface TestCase {
  query: string;
  expectedToContain?: string[];       // ALL of these must appear in the answer
  expectedToContainAny?: string[][];  // For each inner array, AT LEAST ONE must match
  expectFallback?: boolean;           // if true, we expect a grounded-fallback answer
}

const TEST_CASES: TestCase[] = [
  {
    query: "What is your standard shipping time?",
    expectedToContain: ["business days", "processing"],
  },
  {
    query: "Do you offer free shipping?",
    expectedToContain: ["75", "free"],
  },
  {
    // LLM may spell out numbers — accept 'five'/'ten' OR '5'/'10'
    query: "How long does a refund take?",
    expectedToContainAny: [
      ["5", "five"],         // one of these must appear
      ["10", "ten"],         // one of these must appear
      ["business days"],     // this must always appear (put in its own group to require it)
    ],
  },
  {
    query: "Can you cancel my order?",
    // 'cannot'/'can not'/'unable' plus a reference to creating a request
    expectedToContainAny: [
      ["cannot", "can not", "unable", "not cancel"],
      ["request", "cancellation"],
    ],
  },
  {
    query: "How much weight can this shelf hold?",
    expectFallback: true,
  },
  {
    // FAQ-010: 'cannot edit an order / can create a handoff' is grounded KB content.
    // The LLM may answer with the KB policy OR the generic fallback — both are valid.
    query: "Can you add this item to my cart?",
    expectedToContainAny: [
      ["cannot", "can not", "unable", "could not confirm", "do not want to guess"],
    ],
  },
];

// -----------------------------------------------------------------------
// Helper: run one query against the streaming hotpath server
// -----------------------------------------------------------------------
async function runQuery(query: string): Promise<{
  fullText: string;
  firstAudioMs: number | null;
  ragMs: number | null;
  embedMs: number | null;
  qdrantMs: number | null;
  ttftMs: number | null;
  firstSentenceReadyMs: number | null;
  ttsConnectionLatencyMs: number | null;
  ttsFirstAudioMs: number | null;
  browserFirstAudioMs: number | null;
  totalMs: number | null;
}> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(WS_URL);
    const t0 = performance.now();
    const elapsed = () => Math.round(performance.now() - t0);

    let fullText = "";
    let firstAudioMs: number | null = null;
    let ragMs: number | null = null;
    let embedMs: number | null = null;
    let qdrantMs: number | null = null;
    let ttftMs: number | null = null;
    let firstSentenceReadyMs: number | null = null;
    let ttsConnectionLatencyMs: number | null = null;
    let ttsFirstAudioMs: number | null = null;
    let browserFirstAudioMs: number | null = null;
    let totalMs: number | null = null;

    const timeout = setTimeout(() => {
      ws.close();
      reject(new Error(`Query timed out after 15s: "${query}"`));
    }, 15000);

    ws.on("open", () => {
      ws.send(JSON.stringify({ type: "query", text: query }));
    });

    ws.on("message", (raw: Buffer, isBinary: boolean) => {
      if (isBinary) {
        if (firstAudioMs === null) firstAudioMs = elapsed();
        return;
      }

      let msg: any;
      try { msg = JSON.parse(raw.toString()); } catch { return; }

      switch (msg.type) {
        case "assistant_text":
          fullText += msg.text || "";
          break;
        case "metric":
          if (msg.stage === "rag_complete") {
            ragMs = msg.ragLatencyMs;
            embedMs = msg.embedLatencyMs;
            qdrantMs = msg.qdrantLatencyMs;
          }
          if (msg.stage === "gemini_first_token") ttftMs = msg.ttftMs;
          if (msg.stage === "sentence_ready" && msg.sentenceId === 0) firstSentenceReadyMs = msg.sentenceReadyMs;
          if (msg.stage === "tts_http_response" && msg.sentenceId === 0) ttsConnectionLatencyMs = msg.ttsConnectionLatencyMs;
          if (msg.stage === "tts_first_audio_chunk" && msg.sentenceId === 0) ttsFirstAudioMs = msg.ttsFirstAudioMs;
          if (msg.stage === "browser_first_audio") browserFirstAudioMs = msg.firstAudioMs;
          break;
        case "done":
          totalMs = msg.totalMs;
          clearTimeout(timeout);
          ws.close();
          resolve({ fullText, firstAudioMs, ragMs, embedMs, qdrantMs, ttftMs, firstSentenceReadyMs, ttsConnectionLatencyMs, ttsFirstAudioMs, browserFirstAudioMs, totalMs });
          break;
        case "error":
          clearTimeout(timeout);
          ws.close();
          reject(new Error(msg.message));
          break;
      }
    });

    ws.on("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });
  });
}

// -----------------------------------------------------------------------
// Main suite
// -----------------------------------------------------------------------
async function runSuite() {
  console.log("============================================================");
  console.log("Harbor & Pine Streaming RAG - End-to-End Test Suite");
  console.log(`   Server: ${WS_URL}`);
  console.log("============================================================\n");

  let passed = 0;
  let failed = 0;

  // Latency accumulators for summary
  const allEmbed: number[] = [];
  const allQdrant: number[] = [];
  const allTTFT: number[] = [];
  const allSentenceReady: number[] = [];
  const allTTSFirstAudio: number[] = [];
  const allBrowserFirstAudio: number[] = [];

  for (let i = 0; i < TEST_CASES.length; i++) {
    const tc = TEST_CASES[i];
    console.log(`\nTest ${i + 1}/${TEST_CASES.length}: "${tc.query}"`);
    console.log("-".repeat(60));

    try {
      const result = await runQuery(tc.query);

      console.log(`Answer: ${result.fullText.trim()}`);
      console.log(`\nDetailed Latency Breakdown:`);
      console.log(`  Embedding            : ${result.embedMs ?? "N/A"} ms`);
      console.log(`  Qdrant               : ${result.qdrantMs ?? "N/A"} ms`);
      console.log(`  RAG total            : ${result.ragMs ?? "N/A"} ms`);
      console.log(`  Gemini TTFT          : ${result.ttftMs ?? "N/A"} ms`);
      console.log(`  First sentence ready : ${result.firstSentenceReadyMs ?? "N/A"} ms`);
      console.log(`  TTS connection       : ${result.ttsConnectionLatencyMs ?? "N/A"} ms`);
      console.log(`  TTS first audio      : ${result.ttsFirstAudioMs ?? "N/A"} ms`);
      console.log(`  Browser first audio  : ${result.browserFirstAudioMs ?? result.firstAudioMs ?? "N/A"} ms  (target <= ${FIRST_AUDIO_TARGET_MS} ms)`);
      console.log(`  Total pipeline       : ${result.totalMs ?? "N/A"} ms`);

      // Accumulate for averages
      if (result.embedMs !== null) allEmbed.push(result.embedMs);
      if (result.qdrantMs !== null) allQdrant.push(result.qdrantMs);
      if (result.ttftMs !== null) allTTFT.push(result.ttftMs);
      if (result.firstSentenceReadyMs !== null) allSentenceReady.push(result.firstSentenceReadyMs);
      if (result.ttsFirstAudioMs !== null) allTTSFirstAudio.push(result.ttsFirstAudioMs);
      const fa = result.browserFirstAudioMs ?? result.firstAudioMs;
      if (fa !== null) allBrowserFirstAudio.push(fa);

      // --- Correctness checks ---
      const answerLower = result.fullText.toLowerCase();
      let testPassed = true;
      const issues: string[] = [];

      if (tc.expectFallback) {
        const hasFallback =
          answerLower.includes("could not confirm") ||
          answerLower.includes("human support") ||
          answerLower.includes("do not want to guess");
        if (!hasFallback) {
          issues.push("Expected fallback answer but LLM generated a specific response.");
          testPassed = false;
        }
      }

      if (tc.expectedToContain) {
        for (const keyword of tc.expectedToContain) {
          if (!answerLower.includes(keyword.toLowerCase())) {
            issues.push(`Expected answer to contain "${keyword}" but it was missing.`);
            testPassed = false;
          }
        }
      }

      // Each inner array is an OR group — at least one keyword per group must match
      if (tc.expectedToContainAny) {
        for (const group of tc.expectedToContainAny) {
          const matched = group.some(kw => answerLower.includes(kw.toLowerCase()));
          if (!matched) {
            issues.push(`Expected answer to contain at least one of: ${group.map(k => `"${k}"`).join(", ")}`);
            testPassed = false;
          }
        }
      }

      // Latency advisory (non-failing)
      const firstAudioFinal = result.browserFirstAudioMs ?? result.firstAudioMs;
      if (firstAudioFinal !== null && firstAudioFinal > FIRST_AUDIO_TARGET_MS) {
        issues.push(`[Advisory] First audio latency ${firstAudioFinal}ms exceeds ${FIRST_AUDIO_TARGET_MS}ms target.`);
      }

      if (testPassed) {
        console.log(`\n[PASS]`);
        passed++;
      } else {
        const functionalFails = issues.filter(i => !i.startsWith("[Advisory]"));
        if (functionalFails.length > 0) {
          console.log(`\n[FAIL]`);
          issues.forEach((issue) => console.log(`   - ${issue}`));
          failed++;
        } else {
          // Only advisory issues — still a pass
          console.log(`\n[PASS] (with advisory warnings)`);
          issues.forEach((issue) => console.log(`   - ${issue}`));
          passed++;
        }
      }

    } catch (err: any) {
      console.error(`\n[ERROR]: ${err.message}`);
      failed++;
    }
  }

  // Aggregated latency summary
  const avg = (arr: number[]) =>
    arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : null;

  console.log("\n============================================================");
  console.log("Latency Summary (averages across all tests)");
  console.log("============================================================");
  console.log(`  Embedding avg            : ${avg(allEmbed) ?? "N/A"} ms  (target <=150ms)`);
  console.log(`  Qdrant avg               : ${avg(allQdrant) ?? "N/A"} ms`);
  console.log(`  Gemini TTFT avg          : ${avg(allTTFT) ?? "N/A"} ms  (target <=800ms)`);
  console.log(`  First sentence ready avg : ${avg(allSentenceReady) ?? "N/A"} ms`);
  console.log(`  TTS first audio avg      : ${avg(allTTSFirstAudio) ?? "N/A"} ms`);
  console.log(`  Browser first audio avg  : ${avg(allBrowserFirstAudio) ?? "N/A"} ms  (target <=1500ms)`);

  const bottleneck = [
    { name: "Embedding",       ms: avg(allEmbed) },
    { name: "Gemini TTFT",     ms: avg(allTTFT) },
    { name: "TTS first audio", ms: avg(allTTSFirstAudio) },
  ].filter(x => x.ms !== null).sort((a, b) => b.ms! - a.ms!);

  if (bottleneck.length > 0) {
    console.log(`\n  [#1 Bottleneck] ${bottleneck[0].name} — avg ${bottleneck[0].ms}ms`);
    if (bottleneck.length > 1) console.log(`  [#2 Bottleneck] ${bottleneck[1].name} — avg ${bottleneck[1].ms}ms`);
  }

  console.log("\n============================================================");
  console.log(`Results: ${passed} passed / ${failed} failed / ${TEST_CASES.length} total`);
  console.log("============================================================\n");

  process.exit(failed > 0 ? 1 : 0);
}

runSuite().catch((err) => {
  console.error("Suite failed:", err.message || err);
  process.exit(1);
});
