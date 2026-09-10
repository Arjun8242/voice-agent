import { GoogleGenerativeAI } from "@google/generative-ai";
import dotenv from "dotenv";

dotenv.config();

const apiKey = process.env.GEMINI_API_KEY || "";

if (!apiKey) {
  throw new Error("GEMINI_API_KEY is not given in environment.");
}

const genAI = new GoogleGenerativeAI(apiKey);
const EMBEDDING_MODEL = "gemini-embedding-001";

/**
 * Generates 3072-dimension vector embedding for the given text using Google Gemini.
 *
 * @param text The input string to embed
 * @returns Array of 3072 float numbers representing the vector embedding
 */
export async function getEmbedding(text: string): Promise<number[]> {
  const model = genAI.getGenerativeModel({ model: EMBEDDING_MODEL });

  const result = await model.embedContent(text);

  return result.embedding.values;
}
