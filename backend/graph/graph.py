"""builder.py: wire the S7 graph.
 
    START -> ingest -> retrieve -> agent -> respond -> END
 
Dependencies are passed in (see server/main.py for the real ones), so the graph
can be tested with fakes and never imports the retriever or Gemini itself:
    retrieve_fn(query, top_k, topic) -> retrieval result dict
    generate_fn(prompt, system_instruction) -> async iterator of text pieces
    aliases: spoken project name -> project id
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from .state import TurnState
from .nodes.ingest import create_ingest_node
from .nodes.retrieve import create_retrieve_node
from .nodes.agent import create_agent_node
from .nodes.respond import respond_node

def build_graph(retrieve_fn, generate_fn, aliases:dict[str, str], checkpointer = None):
    graph = StateGraph(TurnState)


    graph.add_node("ingest", create_ingest_node(aliases))
    graph.add_node("retrieve", create_retrieve_node(retrieve_fn))
    graph.add_node("agent", create_agent_node(generate_fn))
    graph.add_node("response", respond_node)


    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "retrieve")
    graph.add_edge("retrieve", "agent")
    graph.add_edge("agent", "response")
    graph.add_edge("response", END)

    return graph.compile(checkpointer = checkpointer or InMemorySaver())

    


