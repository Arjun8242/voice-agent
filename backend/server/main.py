"""main.py: FastAPI app — WebSocket server entry point.

"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket

try:
    from server.connection import handle_connection
    from rag.retriever import init_retriever
    from rag.llm import warm_llm
    from providers.tts import warm_tts, create_tts_client
except (ImportError, ModuleNotFoundError):
    from backend.server.connection import handle_connection
    from backend.rag.retriever import init_retriever
    from backend.rag.llm import warm_llm
    from backend.providers.tts import warm_tts, create_tts_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_retriever()
    app.state.tts_client = create_tts_client()
    await asyncio.gather(
        warm_llm(),
        warm_tts(app.state.tts_client),
    )
    print("🚀 Voice agent server running on ws://localhost:3001")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@app.websocket("/")
async def websocket_endpoint(ws: WebSocket) -> None:
    await handle_connection(ws, ws.app.state.tts_client)
