from langgraph.graph import StateGraph, START, END
from models import State
from nodes import orchestrator, worker, reducer, fanout

def create_workflow():
    graph = StateGraph(State)

    graph.add_node("orchestrator", orchestrator)
    graph.add_node("worker", worker)
    graph.add_node("reducer", reducer)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges("orchestrator", fanout, ["worker"])
    graph.add_edge("worker", "reducer")
    graph.add_edge("reducer", END)

    return graph.compile()