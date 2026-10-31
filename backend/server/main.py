"""main.py: FastAPI app — WebSocket server entry point.

S9: loads structured KB data, builds the tool registry, and passes it
to the graph builder so the agent can call tools.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket

try:
    from server.connection import handle_connection
    from rag.retriever import init_retriever, retrieve, project_aliases
    from rag.llm import warm_llm, stream_text
    from graph.graph import build_graph
    from graph.api import router as internal_router
    from providers.tts import warm_tts, create_tts_client
    from tools.registry import build_registry
    from kb.loaders import load_yaml
except (ImportError, ModuleNotFoundError):
    from backend.server.connection import handle_connection
    from backend.rag.retriever import init_retriever, retrieve, project_aliases
    from backend.rag.llm import warm_llm, stream_text
    from backend.graph.graph import build_graph
    from backend.graph.api import router as internal_router
    from backend.providers.tts import warm_tts, create_tts_client
    from backend.tools.registry import build_registry
    from backend.kb.loaders import load_yaml


def _find_kb_dir() -> Path:
    """Locate the knowledge_base directory."""
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "knowledge_base",
        Path("knowledge_base"),
        Path("../knowledge_base"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _find_index_file() -> Path:
    """Locate the kb_index.json file."""
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "data" / "kb_index.json",
        Path("data") / "kb_index.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _load_kb_data() -> dict:
    """Load structured KB files and index chunks for tool registry."""
    import json

    kb_dir = _find_kb_dir()
    structured = kb_dir / "structured"
    errors: list[str] = []

    projects = load_yaml(structured / "projects.yaml", errors) or []
    skills = load_yaml(structured / "skills.yaml", errors) or []
    links = load_yaml(structured / "links.yaml", errors) or []

    if errors:
        print(f"[tools] KB load warnings: {errors}")

    # Load index chunks for getProjectDetail
    index_path = _find_index_file()
    chunks: list[dict] = []
    if index_path.exists():
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            chunks = raw

    # Build project names map (id -> name) for skill evidence display
    project_names: dict[str, str] = {}
    for p in projects:
        if isinstance(p, dict) and "id" in p and "name" in p:
            project_names[p["id"]] = p["name"]

    return {
        "projects": projects,
        "skills": skills,
        "links": links,
        "chunks": chunks,
        "project_names": project_names,
    }


def _build_tool_descriptions() -> list[dict]:
    """Build tool declarations for the Gemini model.
    
    These are plain dicts describing each tool's name, description, and parameters.
    The actual FunctionDeclaration/Tool objects are created by the LLM layer.
    """
    return [
        {
            "name": "searchProjects",
            "description": (
                "Search Arjun's projects by name or technology. "
                "Use this when the visitor asks about projects, what Arjun has built, "
                "or which projects use a specific technology. "
                "For details about a specific project's architecture, decisions, or challenges, "
                "use getProjectDetail instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text search term (matched against name and one_line).",
                    },
                    "tech": {
                        "type": "string",
                        "description": "Technology name to filter by (e.g. 'Redis', 'React').",
                    },
                },
            },
        },
        {
            "name": "getProjectDetail",
            "description": (
                "Get a specific section from a project document. "
                "Use this when the visitor asks about a project's architecture, key decisions, "
                "challenges, limitations, or status. "
                "Requires a project_id (from searchProjects) and a section name. "
                "For a list of projects, use searchProjects instead. "
                "For skills, use getSkills instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project id (e.g. 'beacon', 'fitai', 'valyrian').",
                    },
                    "section": {
                        "type": "string",
                        "description": "Section heading (e.g. 'Overview', 'Architecture', 'Key decisions', "
                        "'Challenges and how they were solved', 'Limitations and not yet done', "
                        "'Status and what is tested').",
                    },
                },
                "required": ["project_id", "section"],
            },
        },
        {
            "name": "getSkills",
            "description": (
                "Look up Arjun's skills. Call with no arguments to list all skills, "
                "or with a skill name to get evidence (which projects demonstrate it). "
                "Use this when the visitor asks whether Arjun knows a technology, "
                "what his skills are, or what experience he has with a specific tool. "
                "For project details, use getProjectDetail instead. "
                "For links, use getLinks instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "Skill name to look up (e.g. 'Redis', 'Python', 'Docker'). "
                        "Omit to list all skills.",
                    },
                },
            },
        },
        {
            "name": "getLinks",
            "description": (
                "Get Arjun's profile links and URLs by type. "
                "Use this when the visitor asks for Arjun's GitHub, LinkedIn, resume, "
                "portfolio, or coding profile. "
                "Available types: portfolio, resume, github_profile, professional_profile, coding_profile. "
                "For project information, use searchProjects instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Link type: portfolio, resume, github_profile, "
                        "professional_profile, or coding_profile.",
                    },
                },
                "required": ["type"],
            },
        },
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_retriever()

    # S9: load KB data and build tool registry
    kb_data = _load_kb_data()
    registry = build_registry(**kb_data)
    tool_defs = _build_tool_descriptions()

    print(f"[tools] registry ready: {registry.names}")

    app.state.graph = build_graph(
        retrieve_fn=retrieve,
        generate_fn=stream_text,
        aliases=project_aliases(),
        registry=registry,
        tool_defs=tool_defs,
    )
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
