import fs from "fs";
import path from "path";
import crypto from "crypto";
import {
  qdrantClient,
  COLLECTION_NAME,
  ensureCollectionExists,
} from "./qdrant.js";
import { getEmbedding } from "./embedder.js";

export interface KnowledgeChunk {
  text: string;
  source: string;
  section: string;
}

/**
 * Rough token estimate.
 * For English text, ~4 characters ≈ 1 token.
 */
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/**
 * Splits a document into chunks targeting ~300–500 tokens.
 */
export function chunkMarkdown(
  filePath: string,
  content: string
): KnowledgeChunk[] {
  const sections = content.split(/\n(?=## )/);
  const chunks: KnowledgeChunk[] = [];

  for (const section of sections) {
    const lines = section.trim().split("\n");

    const sectionName =
      lines[0]?.replace(/^##\s*/, "").trim() || "General";

    const paragraphs = lines
      .slice(1)
      .join("\n")
      .split(/\n\s*\n/)
      .map(p => p.trim())
      .filter(Boolean);

    let buffer = "";

    for (const paragraph of paragraphs) {
      const candidate = buffer
        ? `${buffer}\n\n${paragraph}`
        : paragraph;

      if (estimateTokens(candidate) > 500 && buffer) {
        chunks.push({
          text: buffer,
          source: path.basename(filePath),
          section: sectionName,
        });

        buffer = paragraph;
      } else {
        buffer = candidate;
      }
    }

    if (buffer) {
      chunks.push({
        text: buffer,
        source: path.basename(filePath),
        section: sectionName,
      });
    }
  }

  return chunks;
}

/**
 * Reads knowledge files, creates embeddings and stores them in Qdrant.
 */
export async function ingestKnowledgeBase(
  knowledgeDir: string
): Promise<number> {
  await ensureCollectionExists();

  const files = fs
    .readdirSync(knowledgeDir)
    .filter(file => /\.(md|txt)$/.test(file));

  const points = [];

  for (const file of files) {
    const content = fs.readFileSync(
      path.join(knowledgeDir, file),
      "utf8"
    );

    const chunks = chunkMarkdown(
      path.join(knowledgeDir, file),
      content
    );

    for (const chunk of chunks) {
      const vector = await getEmbedding(chunk.text);

      points.push({
        id: crypto.randomUUID(),
        vector,
        payload: {
          text: chunk.text,
          source: chunk.source,
          section: chunk.section,
        },
      });
    }
  }

  if (!points.length) {
    console.log("No knowledge documents found.");
    return 0;
  }

  await qdrantClient.upsert(COLLECTION_NAME, {
    wait: true,
    points,
  });

  console.log(`Indexed ${points.length} knowledge chunks.`);

  return points.length;
}