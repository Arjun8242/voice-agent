import dotenv from "dotenv";
import { retrieveLocal as retrieve, initLocalRetriever } from "../src/services/rag/local_retriever.js";
import { generateAnswer } from "../src/services/rag/llm.js";

dotenv.config();

const queries = [
  "How long does shipping take?",
  "Do you offer free shipping?",
  "How long do refunds take?",
  "Can you cancel my order?",
  "Can you tell me the weight capacity of this shelf?",
  "How do I add something to my cart?"
];

async function testLLM() {
  await initLocalRetriever();
  console.log("=== LLM Answer Generation Test ===\n");
  
  for (const query of queries) {
    console.log(`Query: "${query}"`);
    console.log("-".repeat(50));
    try {
      const retrievedContext = await retrieve(query, 2);
      const result = await generateAnswer(query, retrievedContext);
      
      console.log(`Answer:\n${result.answer}\n`);
      console.log(`Retrieved Chunks:`);
      result.retrievedChunks.forEach((chunk) => {
        console.log(`  - [${chunk.id}] (Score: ${chunk.score.toFixed(4)})`);
      });
      console.log("=".repeat(50) + "\n");
    } catch (err) {
      console.error(`Error processing query "${query}":`, err);
    }
  }
}

testLLM();
