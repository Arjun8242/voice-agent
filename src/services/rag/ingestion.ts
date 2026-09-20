import fs from "fs";
import path from "path";
import crypto from "crypto";
import {
  qdrantClient,
  COLLECTION_NAME,
  ensureCollectionExists,
} from "./qdrant.js";
import { getEmbedding } from "./embedder.js";

// Deterministic UUID generator from a string
function generateDeterministicUuid(str: string): string {
  const hash = crypto.createHash("md5").update(str).digest("hex");
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

/**
 * Reads knowledge chunks from JSON, creates embeddings and stores them in Qdrant.
 */
export async function ingestKnowledgeBase(
  jsonFilePath: string = path.resolve(process.cwd(), "data", "processed", "harbor_pine_chunks.json")
): Promise<number> {
  await ensureCollectionExists();

  if (!fs.existsSync(jsonFilePath)) {
    console.error(`File not found: ${jsonFilePath}`);
    return 0;
  }

  const fileData = fs.readFileSync(jsonFilePath, "utf8");
  const chunks = JSON.parse(fileData);

  if (!Array.isArray(chunks)) {
    console.error("JSON file does not contain an array of chunks.");
    return 0;
  }

  console.log(`Loading chunks...`);
  console.log(`Found ${chunks.length} chunks.`);
  console.log(`\nEmbedding:`);

  const points = [];
  
  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    console.log(`[${i + 1}/${chunks.length}] ${chunk.id}`);
    
    const textToEmbed = chunk.content;
    const vector = await getEmbedding(textToEmbed);

    points.push({
      id: generateDeterministicUuid(chunk.id),
      vector,
      payload: {
        id: chunk.id,
        type: chunk.type,
        title: chunk.title,
        content: chunk.content,
        source: chunk.source,
        source_type: chunk.source_type,
        // Fallbacks for existing retrieval logic mapping
        text: chunk.content, 
        section: chunk.title
      },
    });
  }

  if (!points.length) {
    console.log("No knowledge documents found.");
    return 0;
  }

  console.log(`\nUpserting into Qdrant...`);
  await qdrantClient.upsert(COLLECTION_NAME, {
    wait: true,
    points,
  });

  console.log(`\nSuccessfully ingested ${points.length} chunks.`);

  return points.length;
}