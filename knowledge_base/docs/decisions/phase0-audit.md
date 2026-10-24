async def retrieve(query: str, top_k: int = 3) -> dict

Inputs -> query, top_k
Output -> query, chunks, combinedContext, latencyms, embedlatencyms, searchlatencyms

added topic as third optional keyword argument in retrieve function

Model Name: BAAI/bge-small-en-v1.5 
Library: sentence-transformers (SentenceTransformer)
Embedding Dimension: 384
Embedding Normalization: normalize_embeddings=True (ensures dot product is identical to cosine similarity)
Query Instruction Prefix: "Represent this sentence for searching relevant passages: " 
Document / Passage Prefix: None (encoded as plain f"{title}\n{content}")
Relevance Threshold (MIN_SCORE): 0.5

3. Framework & Integration Point (Where S7 Hooks In)
Web Framework: FastAPI with uvicorn and WebSockets 

Where Final Transcript becomes an LLM Call (The Pipeline Trace):


Right now, your voice assistant is a straight pipe:

1.You speak into the mic.
2.STT finishes listening and produces the text: "What is Beacon?"
3.That text immediately goes into a simple function called answer_turn(), which searches chunks, calls Gemini, and plays audio.

how it go to answer turn -> ( pehle on_final meh gya udhr se launch_turn meh gya udhr se run_turn meh gya fir udhr se answer_turn meh gya)

toh jb langgraph lagayenge toh is answer_turn ko replace krdenge langgraph agent se which will check calendars, book meetings, show UI cards, and handle complex topics
and acc to S7 pehle agent to text se test krenge fir S11 me voice se hook krenge toh ye hi hai vo Integration point for langgraph agent