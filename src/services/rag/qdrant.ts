import { QdrantClient } from "@qdrant/js-client-rest";
import dotenv from "dotenv";

dotenv.config();

const qdrantUrl = process.env.QDRANT_URL || "http://localhost:6333";
const qdrantApiKey = process.env.QDRANT_API_KEY || undefined;

export const COLLECTION_NAME = "company_knowledge";
export const VECTOR_DIMENSION = 3072; // Gemini gemini-embedding-001 dimension

export const qdrantClient = new QdrantClient({
  url: qdrantUrl,
  apiKey: qdrantApiKey,
});

/**
 * Ensures the Qdrant collection exists with proper vector configurations.
 */
export async function ensureCollectionExists(): Promise<void> {
  const collections = await qdrantClient.getCollections();
  const exists = collections.collections.some(
    (col) => col.name === COLLECTION_NAME
  );

  if (!exists) {
    console.log(`Creating Qdrant collection: "${COLLECTION_NAME}"...`);

    await qdrantClient.createCollection(COLLECTION_NAME, {
      vectors: {
        size: VECTOR_DIMENSION,
        distance: "Cosine",
      },
    });

    console.log(`Collection "${COLLECTION_NAME}" created successfully.`);
  } else {
    console.log(`Qdrant collection "${COLLECTION_NAME}" already exists.`);
  }
}
