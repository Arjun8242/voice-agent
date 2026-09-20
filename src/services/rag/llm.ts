import { GoogleGenerativeAI } from "@google/generative-ai";
import dotenv from "dotenv";
import { RetrievedChunk, RetrievedContext } from "./retriever.js";

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

const FALLBACK_ANSWER = "I could not confirm that from the approved Harbor & Pine information, so I do not want to guess. I can help you request human support.";

export async function generateAnswer(
  query: string,
  retrievedContext: RetrievedContext
): Promise<AnswerGenerationResult> {
  // If no chunks were returned, short-circuit and return fallback.
  if (!retrievedContext.chunks || retrievedContext.chunks.length === 0) {
    return {
      answer: FALLBACK_ANSWER,
      query,
      retrievedChunks: [],
    };
  }

  // Format retrieved chunks according to rules
  const formattedContext = retrievedContext.chunks
    .map((chunk) => {
      const id = chunk.metadata.id || "Unknown";
      const title = chunk.metadata.section || "Untitled";
      return `[${id}]\nTitle: ${title}\nContent:\n${chunk.text}`;
    })
    .join("\n\n");

  const systemInstruction = `You are a Harbor & Pine Living customer-support assistant speaking over the phone.

PRINCIPLES:
1. The retrieved Harbor & Pine context is your ONLY source of truth.
2. Answer the user's question ONLY using information supported by the retrieved context.
3. Do NOT use general world knowledge to fill missing information.
4. Do NOT invent policies, prices, delivery times, product specifications, refund guarantees, exceptions, or procedures.
5. If the retrieved context does not contain enough information to answer:
   - Clearly say that the information could not be confirmed.
   - Do not guess.
   - Offer human support when appropriate.
6. Follow the limitations contained in the retrieved Harbor & Pine content.
7. If the retrieved context says that a human must review something, do not claim that you (the assistant) completed the action.
8. Do not claim that a refund, cancellation, address change, order edit, payment action, privacy request, replacement, compensation, or policy exception has been completed when the context says the assistant cannot perform it.

VOICE RESPONSE STYLE:
- Keep responses concise.
- Prefer approximately 1-3 sentences when possible.
- Generally stay around 40-100 words.
- Give the direct answer first.
- Use natural conversational English.
- No Markdown.
- No bullet points.
- No numbered lists.
- No headings.
- No tables.
- Avoid unnecessary repetition.
- Avoid phrases like "According to the retrieved context".
- Do not mention Qdrant, embeddings, RAG, chunks, or internal architecture.
- Do not sound robotic.
The answer should sound like something a customer-support representative would naturally say over the phone.
If you do not know the answer, use the approved fallback wording: "I could not confirm that from the approved Harbor & Pine information, so I do not want to guess. I can help you request human support."
`;

  const userPrompt = `Customer question:
${query}

Retrieved Harbor & Pine information:
${formattedContext}

Generate the final customer-facing answer.`;

  try {
    const model = genAI.getGenerativeModel({
      model: GEMINI_MODEL,
      systemInstruction: { parts: [{ text: systemInstruction }], role: "system" },
    });

    const response = await model.generateContent(userPrompt);
    const answer = response.response.text().trim();

    // Map extracted chunk metadata for the result
    const retrievedChunks = retrievedContext.chunks.map((c) => ({
      id: c.metadata.id || "Unknown",
      score: c.score,
    }));

    // If the LLM returned an empty response for some reason
    if (!answer) {
      return {
        answer: FALLBACK_ANSWER,
        query,
        retrievedChunks,
      };
    }

    return {
      answer,
      query,
      retrievedChunks,
    };
  } catch (error) {
    console.error("LLM Generation failed:", error);
    // Return fallback on LLM failure instead of crashing silently
    return {
      answer: FALLBACK_ANSWER,
      query,
      retrievedChunks: retrievedContext.chunks.map((c) => ({
        id: c.metadata.id || "Unknown",
        score: c.score,
      })),
    };
  }
}
