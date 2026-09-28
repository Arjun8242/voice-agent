import fs from "fs";
import path from "path";
import { pipeline } from "@huggingface/transformers";
import type { RetrievedChunk, RetrievedContext } from "./retriever.js";
 
const MODEL = "Xenova/bge-small-en-v1.5";
// bge models want this prefix on the QUERY only (not on the documents)
const QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";
const MAX_CHAR_CAP = 3000; // same ~1000-token cap as retriever.ts
 
interface Item {
  id: string;
  title: string;
  text: string;
  source?: string;
  vec: Float32Array;
}
 
let extractor: any = null;
let items: Item[] = [];
 
// Cache of query-text -> embedding promise. Lets you start embedding a stable
// partial transcript early; retrieveLocal() then reuses it if the final text matches.
const queryCache = new Map<string, Promise<Float32Array>>();
const CACHE_MAX = 200;
 
const normalize = (t: string) =>
  t.trim().toLowerCase().replace(/\s+/g, " ").replace(/[?.!,]+$/g, "");
 
async function embed(text: string): Promise<Float32Array> {
  const out = await extractor(text, { pooling: "cls", normalize: true });
  return Float32Array.from(out.data as Float32Array);
}
 
function embedQuery(query: string): Promise<Float32Array> {
  const key = normalize(query);
  let p = queryCache.get(key);
  if (!p) {
    p = embed(QUERY_PREFIX + query);
    queryCache.set(key, p);
    if (queryCache.size > CACHE_MAX) {
      queryCache.delete(queryCache.keys().next().value as string);
    }
  }
  return p;
}
 
/** Call from the STT partial handler once a partial has been stable for a moment. */
export function prefetchQuery(partial: string): void {
  if (extractor && partial.trim()) void embedQuery(partial);
}
 
/** Call once at server start, BEFORE opening the WebSocket server. */
export async function initLocalRetriever(
  jsonFilePath: string = path.resolve(process.cwd(), "data", "KB_chunks", "harbor_pine_chunks.json")
): Promise<void> {
  const t0 = performance.now();
  extractor = await pipeline("feature-extraction", MODEL, { dtype: "q8" });
 
  const chunks = JSON.parse(fs.readFileSync(jsonFilePath, "utf8"));
  items = [];
  for (const c of chunks) {
    items.push({
      id: c.id,
      title: c.title,
      text: c.content,
      source: c.source,
      // title + content helps short FAQ chunks match; documents get no query prefix
      vec: await embed(`${c.title}\n${c.content}`),
    });
  }
 
  await embedQuery("warm up"); // first inference is slower; pay for it now
  console.log(
    `[localRetriever] ready: ${items.length} chunks, ${Math.round(performance.now() - t0)} ms`
  );
}
 
export async function retrieveLocal(query: string, topK: number = 3): Promise<RetrievedContext> {
  if (!extractor) throw new Error("Call initLocalRetriever() before retrieveLocal()");
  const t0 = performance.now();
 
  const q = await embedQuery(query);
  const t1 = performance.now();
 
  // vectors are normalized, so dot product == cosine similarity
  const scored = items
    .map((it) => {
      let s = 0;
      for (let i = 0; i < q.length; i++) s += q[i] * it.vec[i];
      return { it, s };
    })
    .sort((a, b) => b.s - a.s)
    .slice(0, topK);
  const t2 = performance.now();
 
  const chunks: RetrievedChunk[] = [];
  let combinedContext = "";
  for (const { it, s } of scored) {
    if (combinedContext.length + it.text.length > MAX_CHAR_CAP) continue;
    chunks.push({
      text: it.text,
      score: s,
      metadata: { source: it.source, section: it.title, id: it.id },
    });
    combinedContext += `[Source: ${it.title}]\n${it.text}\n\n`;
  }
 
  const r = (n: number) => Number(n.toFixed(2));
  return {
    query,
    chunks,
    combinedContext: combinedContext.trim(),
    latencyMs: r(t2 - t0),
    embedLatencyMs: r(t1 - t0),
    qdrantLatencyMs: r(t2 - t1), // kept under this name so hotpath.ts metrics still work; it's the in-memory search time now
  };
}