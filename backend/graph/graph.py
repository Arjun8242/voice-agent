"""builder.py: wire the S7+S9 graph.
 
    START -> ingest -> retrieve -> agent <-> tools -> respond -> END
 
Dependencies are passed in (see server/main.py for the real ones), so the graph
can be tested with fakes and never imports the retriever or Gemini itself:
    retrieve_fn(query, top_k, topic) -> retrieval result dict
    generate_fn(prompt, system_instruction, tools=None) -> async iterator of text or awaitable dict
    aliases: spoken project name -> project id
    registry: ToolRegistry for the tools node (None = no tools)
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from .state import TurnState
from .nodes.ingest import create_ingest_node
from .nodes.retrieve import create_retrieve_node
from .nodes.agent import create_agent_node, MAX_TOOL_STEPS
from .nodes.respond import respond_node


def _should_use_tools(state: dict) -> str:
    """Conditional edge after agent: go to tools or respond."""
    pending = state.get("_pending_tool_calls", [])
    tool_steps = state.get("tool_steps", 0)

    if pending and tool_steps < MAX_TOOL_STEPS:
        return "tools"
    return "respond"


def build_graph(
    retrieve_fn,
    generate_fn,
    aliases: dict[str, str],
    checkpointer=None,
    registry=None,
    tool_defs: list[dict] | None = None,
):
    graph = StateGraph(TurnState)

    graph.add_node("ingest", create_ingest_node(aliases))
    graph.add_node("retrieve", create_retrieve_node(retrieve_fn))
    graph.add_node("agent", create_agent_node(generate_fn, tool_defs=tool_defs))
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "retrieve")
    graph.add_edge("retrieve", "agent")

    if registry is not None:
        from .nodes.tools import create_tools_node

        graph.add_node("tools", create_tools_node(registry))
        graph.add_conditional_edges("agent", _should_use_tools, {"tools": "tools", "respond": "respond"})
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", "respond")

    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
