import dotenv from "dotenv";
import { retrieve } from "../src/services/rag/retriever.js";

dotenv.config();

const queries = [
  "How long does shipping take?",
  "Do I get free shipping?",
  "Can I return something I bought?",
  "How long will my refund take?",
  "Can you cancel my order?",
  "My product arrived damaged.",
];

async function testRetrieval() {
  console.log("=== Retrieval Test ===");
  for (const query of queries) {
    console.log(`\nQuery: "${query}"`);
    try {
      const result = await retrieve(query, 2);
      result.chunks.forEach((chunk, i) => {
        console.log(`  [Chunk ${i + 1}] ID: ${chunk.metadata.id} | Score: ${chunk.score.toFixed(4)} | Title: ${chunk.metadata.section}`);
      });
    } catch (err) {
      console.error(err);
    }
  }
}

testRetrieval();
