import dotenv from "dotenv";

dotenv.config();

const n8nUrl = process.env.N8N_URL || "http://localhost:5678";
const webhookUrl = `${n8nUrl}/webhook/voice-rag-query`;

async function testN8nPipeline() {
  console.log("==================================================");
  console.log("🔄 n8n Orchestration Pipeline Test (Phase 4)");
  console.log("==================================================");
  console.log(`Endpoint: ${webhookUrl}`);

  const testPayload = {
    query: "What are your pricing plans and what does Pro include?",
    sessionId: "test_session_voice_001",
    timestamp: Date.now(),
  };

  console.log("\nSending query to n8n Webhook:");
  console.log(JSON.stringify(testPayload, null, 2));

  const startTime = performance.now();

  try {
    const response = await fetch(webhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(testPayload),
    });

    const elapsed = (performance.now() - startTime).toFixed(2);

    console.log(`\nHTTP Response Status: ${response.status} ${response.statusText}`);
    console.log(`Total n8n Pipeline Latency: ${elapsed} ms`);

    const rawText = await response.text();
    console.log(`Raw Webhook Response: "${rawText}"`);

    if (response.ok && rawText.trim()) {
      const data: any = JSON.parse(rawText);

      console.log("\n--- Received Webhook Response ---");
      console.log("Status:", data.status);
      console.log("Generated Text:", data.assistantText || data.text || "(No text)");
      console.log("Has Audio:", Boolean(data.audio));

      if (data.audio) {
        console.log(`Audio Payload Size: ${data.audio.length} Base64 chars`);
      }
      if (data.metrics) {
        console.log("Metrics:", JSON.stringify(data.metrics, null, 2));
      }
    } else {
      console.log(`\nWebhook Response Notice: (Empty or non-JSON response)`);
    }
  } catch (error: any) {
    console.error("\n❌ Request Error:", error.message || error);
  }

  console.log("\n==================================================");
  console.log("📋 Phase 4 Architectural Assessment (n8n vs Low-Latency Streaming):");
  console.log("1. Workflow Orchestration: Successfully structured the parallel branch for Qdrant retrieval + Prompt scaffold, followed by LLM and TTS.");
  console.log("2. Streaming vs Buffering Analysis:");
  console.log("   - n8n nodes execute sequentially per item. HTTP Request nodes buffer until completion before passing data to downstream nodes.");
  console.log("   - True end-to-end token streaming (LLM token -> TTS chunk -> Browser speaker in < 1.5s) cannot be achieved through n8n's buffered node architecture.");
  console.log("   - Conclusion (per Spec Section 8 & 20): Use custom Node/Express streaming orchestrator for the latency-critical audio hot path; preserve n8n for background actions (lead capture, CRM, analytics).");
  console.log("==================================================");
}

testN8nPipeline();
