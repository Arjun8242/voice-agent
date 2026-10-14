import { WebSocketServer } from "ws";
import { initLocalRetriever } from "../services/rag/local_retriever.js";
import { PORT } from "../config.js";
import { handleConnection } from "./connection.js";

await initLocalRetriever();

const wss = new WebSocketServer({ port: PORT });
wss.on("connection", handleConnection);

console.log(`🚀 Voice agent server running on ws://localhost:${PORT}`);
