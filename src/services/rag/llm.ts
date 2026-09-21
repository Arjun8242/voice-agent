import { GoogleGenerativeAI } from "@google/generative-ai";
import dotenv from "dotenv";
import { RetrievedContext } from "./retriever.js";

dotenv.config();

const apiKey = process.env.GEMINI_API_KEY || "";
if (!apiKey) {
  console.warn("GEMINI_API_KEY is not set in the environment.");
}

const genAI = new GoogleGenerativeAI(apiKey);
const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-3.5-flash-lite";

export interface AnswerGenerationResult {
  answer: string;
  query: string;
  retrievedChunks: {
    id: string;
    score: number;
  }[];
}

// Conversation turn — matches the Turn interface in hotpath.ts
export interface Turn {
  role: "user" | "assistant";
  text: string;
}

export const FALLBACK_ANSWER =
  "I could not confirm that from the approved Harbor & Pine information, so I do not want to guess. I can help you request human support.";

// -----------------------------------------------------------------------
// Shared: build the grounded system instruction (Harbor & Pine rules)
// -----------------------------------------------------------------------
export function buildSystemInstruction(): string {
  return `You are the phone support assistant for Harbor & Pine Living.

  Answer ONLY from the provided context. Never use outside knowledge or invent policies, prices, times, specifications, guarantees, or exceptions. Keep any limits the context states (estimates, "not guaranteed", "subject to review").
  If the context does not cover the question, reply with exactly: "I could not confirm that from the approved Harbor & Pine information, so I do not want to guess. I can help you request human support."
  If the context says a human must handle something, say you cannot do it yourself but can start a request. Never say a refund, cancellation, change, or exception has been completed or promised.
  Speak naturally in 1 to 3 short sentences of plain text, direct answer first. No lists, headings, or Markdown. Do not mention the context, sources, or how you work.`;
}

// -----------------------------------------------------------------------
// Shared: format retrieved chunks into readable LLM context
// -----------------------------------------------------------------------
export function formatRetrievedContext(retrievedContext: RetrievedContext): string {
  if (!retrievedContext.chunks || retrievedContext.chunks.length === 0) {
    return "No relevant Harbor & Pine information was found for this query.";
  }

  return retrievedContext.chunks
    .map((chunk) => {
      const id = chunk.metadata.id || "Unknown";
      const title = chunk.metadata.section || "Untitled";
      return `[${id}] ${title}\n${chunk.text}`;
    })
    .join("\n\n");
}

// -----------------------------------------------------------------------
// Shared: format conversation history into prompt text
// -----------------------------------------------------------------------
function formatHistory(history: Turn[]): string {
  if (!history || history.length === 0) return "";
  return (
    "Recent conversation:\n" +
    history.map((t) => `${t.role === "user" ? "Customer" : "Assistant"}: ${t.text}`).join("\n") +
    "\n\n"
  );
}

// -----------------------------------------------------------------------
// Non-streaming: generateAnswer (used by test-llm.ts, batch tests)
// -----------------------------------------------------------------------
export async function generateAnswer(
  query: string,
  retrievedContext: RetrievedContext,
  history: Turn[] = []
): Promise<AnswerGenerationResult> {
  const retrievedChunks = (retrievedContext.chunks || []).map((c) => ({
    id: c.metadata.id || "Unknown",
    score: c.score,
  }));

  if (!retrievedContext.chunks || retrievedContext.chunks.length === 0) {
    return { answer: FALLBACK_ANSWER, query, retrievedChunks: [] };
  }

  const systemInstruction = buildSystemInstruction();
  const formattedContext = formatRetrievedContext(retrievedContext);
  const historyText = formatHistory(history);

  const userPrompt = `${historyText}Retrieved Harbor & Pine information:\n${formattedContext}\n\nCustomer question: ${query}\n\nGenerate the customer-facing answer.`;

  try {
    const model = genAI.getGenerativeModel({
      model: GEMINI_MODEL,
      systemInstruction: { parts: [{ text: systemInstruction }], role: "system" },
      generationConfig: { temperature: 0.3, maxOutputTokens: 150 },
    });

    const response = await model.generateContent(userPrompt);
    const answer = response.response.text().trim();

    if (!answer) {
      return { answer: FALLBACK_ANSWER, query, retrievedChunks };
    }

    return { answer, query, retrievedChunks };
  } catch (error) {
    console.error("LLM Generation failed:", error);
    return { answer: FALLBACK_ANSWER, query, retrievedChunks };
  }
}

// -----------------------------------------------------------------------
// Streaming: generateAnswerStream
// Returns the raw stream from Gemini so hotpath.ts can forward tokens
// incrementally to the sentence buffer → TTS → browser.
// -----------------------------------------------------------------------
export async function generateAnswerStream(
  query: string,
  retrievedContext: RetrievedContext,
  history: Turn[] = []
) {
  const systemInstruction = buildSystemInstruction();
  const formattedContext = formatRetrievedContext(retrievedContext);
  const historyText = formatHistory(history);

  const userPrompt = `${historyText}Retrieved Harbor & Pine information:\n${formattedContext}\n\nCustomer question: ${query}\n\nGenerate the customer-facing answer.`;

  const model = genAI.getGenerativeModel({
    model: GEMINI_MODEL,
    systemInstruction: { parts: [{ text: systemInstruction }], role: "system" },
    generationConfig: { temperature: 0.3, maxOutputTokens: 150 },
  });

  // Returns StreamGenerateContentResult — caller iterates result.stream
  return model.generateContentStream(userPrompt);
}
