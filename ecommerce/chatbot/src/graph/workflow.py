
from langgraph.graph import StateGraph, START, END
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.graph.nodes import retrieve, generate, update_state_node

def create_graph():
    """Builds the LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("update_state", update_state_node)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("generate", generate)

    # Add Edges
    workflow.add_edge(START, "update_state")
    workflow.add_edge("update_state", "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    # Compile
    app = workflow.compile()
    return app

# Singleton-like access if needed
graph_app = create_graph()
