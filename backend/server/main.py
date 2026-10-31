"""main.py: FastAPI app — WebSocket server entry point.

"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket

try:
    from server.connection import handle_connection
    from rag.retriever import init_retriever, retrieve, project_aliases
    from rag.llm import warm_llm, stream_text
    from graph.graph import build_graph
    from graph.api import router as internal_router
    from providers.tts import warm_tts, create_tts_client
except (ImportError, ModuleNotFoundError):
    from backend.server.connection import handle_connection
    from backend.rag.retriever import init_retriever, retrieve, project_aliases
    from backend.rag.llm import warm_llm, stream_text
    from backend.graph.graph import build_graph
    from backend.graph.api import router as internal_router
    from backend.providers.tts import warm_tts, create_tts_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_retriever()
    app.state.graph = build_graph(retrieve_fn=retrieve, generate_fn=stream_text, aliases=project_aliases())
    app.state.tts_client = create_tts_client()
    await asyncio.gather(
        warm_llm(),
        warm_tts(app.state.tts_client),
    )
    print("[server] Voice agent server running on ws://localhost:3001")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(internal_router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@app.websocket("/")
async def websocket_endpoint(ws: WebSocket) -> None:
    await handle_connection(ws, ws.app.state.tts_client)
