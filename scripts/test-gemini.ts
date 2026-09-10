import dotenv from "dotenv";
import { GoogleGenerativeAI } from "@google/generative-ai";

dotenv.config();

const apiKey = process.env.GEMINI_API_KEY;
const modelName = process.env.GEMINI_MODEL || "gemini-2.5-flash";

if (!apiKey) {
  console.error("❌ Error: GEMINI_API_KEY not found in environment.");
  process.exit(1);
}

async function testGeminiStreaming() {
  console.log("==================================================");
  console.log("⚡ Gemini Standalone Streaming Benchmark (Phase 2.1)");
  console.log("==================================================");
  console.log(`Model: ${modelName}`);
  console.log(`Prompt: "What is your pricing model? Explain in 2 concise sentences."\n`);

  const genAI = new GoogleGenerativeAI(apiKey!);
  const model = genAI.getGenerativeModel({
    model: modelName!,
    generationConfig: {
      maxOutputTokens: 150,
      temperature: 0.3,
    },
  });

  const prompt = "What is your pricing model? Explain in 2 concise sentences.";
  
  const startTime = performance.now();
  let firstChunkTime: number | null = null;
  let chunkCount = 0;
  let fullResponse = "";

  console.log("⏳ Sending streaming request to Gemini...");

  try {
    const result = await model.generateContentStream(prompt);
    
    for await (const chunk of result.stream) {
      const now = performance.now();
      if (firstChunkTime === null) {
        firstChunkTime = now;
        const ttft = (firstChunkTime - startTime).toFixed(2);
        console.log(`\n🚀 [TTFT] First token received in ${ttft} ms\n--- Streamed Content ---`);
      }
      chunkCount++;
      const text = chunk.text();
      process.stdout.write(text);
      fullResponse += text;
    }

    const endTime = performance.now();
    const totalLatency = (endTime - startTime).toFixed(2);
    const ttft = firstChunkTime ? (firstChunkTime - startTime).toFixed(2) : "N/A";

    console.log("\n------------------------");
    console.log("📊 Latency & Stream Metrics:");
    console.log(`- Request Start -> First Token (TTFT): ${ttft} ms (Target: <= 800 ms)`);
    console.log(`- Total Duration: ${totalLatency} ms`);
    console.log(`- Chunks received: ${chunkCount}`);
    console.log(`- Total Response Length: ${fullResponse.length} chars`);
    
    if (firstChunkTime && (firstChunkTime - startTime) <= 800) {
      console.log(`✅ TTFT Target PASSED (<= 800 ms)`);
    } else {
      console.log(`⚠️ TTFT exceeded 800 ms target or first token was not measured.`);
    }
  } catch (error: any) {
    console.error("\n❌ Gemini Streaming Error:", error?.message || error);
    if (error?.status) console.error("HTTP Status:", error.status);
  }
}

testGeminiStreaming();
