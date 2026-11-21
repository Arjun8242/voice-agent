"""main.py: FastAPI app — WebSocket server entry point.

"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket

try:
    from booking.execute import BookingExecutor
    from booking.store import BookingStore
    from gcal import create_calendar
    from graph.api import router as internal_router
    from graph.graph import build_graph
    from graph.nodes.booking_gate import create_booking_gate_node
    from providers.tts import create_tts_client, warm_tts
    from rag.llm import stream_text, warm_llm
    from rag.retriever import init_retriever, project_aliases, retrieve
    from server.connection import handle_connection
    from tools.kb_data import load_kb_data, load_scheduling
    from tools.registry import build_registry
except (ImportError, ModuleNotFoundError):
    from backend.booking.execute import BookingExecutor
    from backend.booking.store import BookingStore
    from backend.gcal import create_calendar
    from backend.graph.api import router as internal_router
    from backend.graph.graph import build_graph
    from backend.graph.nodes.booking_gate import create_booking_gate_node
    from backend.providers.tts import create_tts_client, warm_tts
    from backend.rag.llm import stream_text, warm_llm
    from backend.rag.retriever import init_retriever, project_aliases, retrieve
    from backend.server.connection import handle_connection
    from backend.tools.kb_data import load_kb_data, load_scheduling
    from backend.tools.registry import build_registry

from functools import partial

from backend.config import CORS_ORIGINS
from backend.graph.interview.graph import build_interview_graph
from backend.interview.analyze import ANALYSIS_MAX_TOKENS
from backend.interview.evaluate import EVALUATOR_MAX_TOKENS, evaluate_interview
from backend.server.interview_upload import allow_page_origins
from backend.server.interview_upload import router as interview_upload_router

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"
BOOKINGS_DB = Path(__file__).resolve().parents[2] / "data" / "bookings.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_retriever()
    scheduling = load_scheduling(KB_DIR)
    # nothing touches a calendar or the bookings table until booking is enabled
    calendar = create_calendar() if scheduling.enabled else None
    store = BookingStore(BOOKINGS_DB) if scheduling.enabled else None
    kb = load_kb_data(KB_DIR)
    registry = build_registry(kb, calendar=calendar, scheduling=scheduling, store=store)
    gate = create_booking_gate_node(store, calendar, scheduling) if scheduling.enabled else None
    app.state.executor = BookingExecutor(store, calendar, scheduling) if scheduling.enabled else None
    app.state.graph = build_graph(
        retrieve_fn=retrieve, generate_fn=stream_text, aliases=project_aliases(), registry=registry, gate=gate,
    )
    app.state.interview_plans = {}  # session id -> InterviewPlan, filled by POST /interview/upload
    app.state.upload_history = {}  # client address -> upload times, for the upload's rate limit
    app.state.analyzer = partial(stream_text, max_tokens=ANALYSIS_MAX_TOKENS)
    app.state.interview_graph = build_interview_graph(stream_text)
    app.state.evaluator = partial(evaluate_interview, generate_fn=partial(stream_text, max_tokens=EVALUATOR_MAX_TOKENS))
    app.state.tts_client = create_tts_client()
    await asyncio.gather(
        warm_llm(),
        warm_tts(app.state.tts_client),
    )
    print("[server] Voice agent server running on ws://localhost:3001")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(internal_router)
app.include_router(interview_upload_router)
allow_page_origins(app, CORS_ORIGINS)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@app.websocket("/")
async def websocket_endpoint(ws: WebSocket) -> None:
    await handle_connection(ws, ws.app.state.tts_client, ws.app.state.graph, ws.app.state.executor,
                            interview_graph=ws.app.state.interview_graph, evaluator=ws.app.state.evaluator,
                            interview_plans=ws.app.state.interview_plans)
