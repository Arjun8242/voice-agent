"""builder.py: wire the S7 + S9 + S14 graph.

    START -> ingest -> retrieve -> agent -> response -> END
               |                     ^  |       ^
               |                     |  v       |   (agent asked for tools and tool_steps < cap)
               |                     tools      |
               '--> booking_gate ---------------'   (a click on a booking card; no LLM)

Dependencies are passed in (see server/main.py for the real ones), so the graph
can be tested with fakes and never imports the retriever or the LLM itself:
    retrieve_fn(query, top_k, topic) -> retrieval result dict
    generate_fn(prompt, system_instruction, tools, tool_calls) -> async iterator of text pieces and tool-call dicts
    aliases: spoken project name -> project id
    registry: tools.registry.ToolRegistry, or None for the S8 graph without tools
    gate: the booking_gate node (nodes/booking_gate.py), or None while booking is disabled
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from .state import TurnState
from .nodes.ingest import create_ingest_node
from .nodes.retrieve import create_retrieve_node
from .nodes.agent import create_agent_node
from .nodes.respond import respond_node
from .nodes.tools import MAX_TOOL_STEPS, create_tools_node


def after_agent(state: dict) -> str:
    """Design doc 4.3: tool calls and tool_steps < cap -> tools; otherwise -> response."""
    if state.get("pending_tool_calls") and state.get("tool_steps", 0) < MAX_TOOL_STEPS:
        return "tools"
    return "response"


def after_ingest(state: dict, has_gate: bool) -> str:
    """A click goes to the gate; without one (booking disabled) it gets the error reply, never the model."""
    if not state.get("ui_action"):
        return "retrieve"
    return "booking_gate" if has_gate else "response"


def build_graph(retrieve_fn, generate_fn, aliases:dict[str, str], checkpointer = None, registry = None, gate = None):
    graph = StateGraph(TurnState)
    tools = registry.declarations() if registry is not None else None


    graph.add_node("ingest", create_ingest_node(aliases))
    graph.add_node("retrieve", create_retrieve_node(retrieve_fn))
    graph.add_node("agent", create_agent_node(generate_fn, tools))
    graph.add_node("response", respond_node)


    graph.add_edge(START, "ingest")
    targets = ["retrieve", "response"]
    if gate is not None:
        graph.add_node("booking_gate", gate)
        graph.add_edge("booking_gate", "response")
        targets.append("booking_gate")
    graph.add_conditional_edges("ingest", lambda state: after_ingest(state, gate is not None), targets)
    graph.add_edge("retrieve", "agent")
    if registry is not None:
        graph.add_node("tools", create_tools_node(registry))
        graph.add_conditional_edges("agent", after_agent, ["tools", "response"])
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", "response")
    graph.add_edge("response", END)

    return graph.compile(checkpointer = checkpointer or InMemorySaver())




