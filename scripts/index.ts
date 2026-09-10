import { spawn } from "child_process";
import path from "path";

interface TestOption {
  name: string;
  script: string;
  description: string;
}

const tests: TestOption[] = [
  {
    name: "Gemini Standalone Streaming (Phase 2.1)",
    script: "scripts/test-gemini.ts",
    description: "Evaluates Gemini streaming TTFT and chunk delivery.",
  },
  {
    name: "Sarvam TTS Standalone (Phase 2.2)",
    script: "scripts/test-sarvam-tts.ts",
    description: "Tests Sarvam TTS REST and streaming audio generation.",
  },
  {
    name: "RAG Ingestion & Retrieval (Phase 3)",
    script: "scripts/test-rag.ts",
    description: "Indexes knowledge into Qdrant and tests retrieval latency.",
  },
  {
    name: "n8n Pipeline Evaluation (Phase 4)",
    script: "scripts/test-n8n-pipeline.ts",
    description: "Assesses n8n workflow orchestration and streaming viability.",
  },
];

async function runScript(scriptPath: string): Promise<void> {
  return new Promise((resolve) => {
    console.log(`\n==================================================`);
    console.log(`▶ Running: ${scriptPath}`);
    console.log(`==================================================\n`);

    const isWindows = process.platform === "win32";
    const npxCmd = isWindows ? "npx.cmd" : "npx";

    const proc = spawn(npxCmd, ["tsx", scriptPath], {
      stdio: "inherit",
      shell: isWindows,
    });

    proc.on("close", (code) => {
      resolve();
    });
  });
}

async function runAll() {
  console.log("==================================================");
  console.log("🚀 Running AI Voice RAG Assistant Test Suite");
  console.log("==================================================");

  for (const t of tests) {
    console.log(`\n• ${t.name}: ${t.description}`);
    await runScript(t.script);
  }

  console.log("\n==================================================");
  console.log("🏁 All Tests Completed Successfully.");
  console.log("==================================================");
}

runAll();
