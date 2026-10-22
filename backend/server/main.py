"""main.py: FastAPI app — WebSocket server entry point.

Corresponds to src/server/index.ts.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket

try:
    from server.connection import handle_connection
    from services.rag.local_retriever import init_retriever
except (ImportError, ModuleNotFoundError):
    from backend.server.connection import handle_connection
    from backend.services.rag.local_retriever import init_retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_retriever()
    print("🚀 Voice agent server running on ws://localhost:3001")
    yield


app = FastAPI(lifespan=lifespan)


@app.websocket("/")
async def websocket_endpoint(ws: WebSocket) -> None:
    await handle_connection(ws)
