from langgraph.graph import StateGraph, START, END
from models import State
from nodes import orchestrator_node, worker_node, reducer_node, fanout, router_node, research_node, route_next

def create_workflow():
    graph = StateGraph(State)

    graph.add_node("router", router_node)
    graph.add_node("research", research_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("worker", worker_node)
    graph.add_node("reducer", reducer_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
    graph.add_edge("research", "orchestrator")
    graph.add_conditional_edges("orchestrator", fanout, ["worker"])
    graph.add_edge("worker", "reducer")
    graph.add_edge("reducer", END)

    return graph.compile()