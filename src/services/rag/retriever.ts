import { qdrantClient, COLLECTION_NAME } from "./qdrant.js";
import { getEmbedding } from "./embedder.js";

export interface RetrievedChunk {
  text: string;
  score: number;
  metadata: {
    source?: string;
    section?: string;
  };
}

export interface RetrievedContext {
  query: string;
  chunks: RetrievedChunk[];
  combinedContext: string;
  latencyMs: number;
}

/**
 * Retrieves the most relevant knowledge chunks from Qdrant for a given query.
 *
 * @param query The search query string
 * @param topK Number of top chunks to return (default: 3)
 * @returns RetrievedContext object with chunks, combined text, and latency
 */
export async function retrieve(
  query: string,
  topK: number = 3
): Promise<RetrievedContext> {
  const startTime = performance.now();

  // 1. Generate query embedding
  const queryVector = await getEmbedding(query);

  // 2. Query Qdrant vector database using universal query API
  const response = await qdrantClient.query(COLLECTION_NAME, {
    query: queryVector,
    limit: topK,
    with_payload: true,
  });

  const latencyMs = Number((performance.now() - startTime).toFixed(2));

  // 3. Format and cap context (keep context concise, under 1000 tokens)
  const chunks: RetrievedChunk[] = [];
  let combinedContext = "";
  const MAX_CHAR_CAP = 3000; // ~750-1000 tokens

  for (const hit of response.points) {
    const payload = hit.payload as {
      text?: string;
      source?: string;
      section?: string;
    };

    const chunkText = payload?.text || "";

    if (combinedContext.length + chunkText.length <= MAX_CHAR_CAP) {
      chunks.push({
        text: chunkText,
        score: hit.score ?? 0,
        metadata: {
          source: payload?.source,
          section: payload?.section,
        },
      });

      combinedContext += `[Source: ${payload?.section || "FAQ"}]\n${chunkText}\n\n`;
    }
  }

  return {
    query,
    chunks,
    combinedContext: combinedContext.trim(),
    latencyMs,
  };
}
