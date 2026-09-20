import dotenv from "dotenv";
import { ingestKnowledgeBase } from "../src/services/rag/ingestion.js";

dotenv.config();

async function runIngestion() {
  try {
    await ingestKnowledgeBase();
    process.exit(0);
  } catch (err) {
    console.error("Ingestion failed:", err);
    process.exit(1);
  }
}

runIngestion();
