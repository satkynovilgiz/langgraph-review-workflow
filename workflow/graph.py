"""Wires the agents together into a LangGraph graph.

    START -> planner -> writer -> reviewer --(revise)--> writer
                                          \\--(finalise)--> finaliser -> END
"""

from langgraph.graph import END, START, StateGraph

from .nodes import make_nodes
from .state import WorkflowState


def route_after_review(state: WorkflowState) -> str:
    """The CONDITIONAL EDGE: after the reviewer, where do we go next?

    The reviewer node already applied the checklist rule and set `status`:
      - "revising"            -> back to the writer with feedback
      - "approved"            -> finaliser
      - "needs_human_review"  -> finaliser (rejected MAX_REVISIONS times; stop looping)
    """
    return "writer" if state["status"] == "revising" else "finaliser"


def build_graph(llm):
    nodes = make_nodes(llm)
    graph = StateGraph(WorkflowState)

    for name, fn in nodes.items():
        graph.add_node(name, fn)

    # Fixed edges: always go this way.
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "writer")
    graph.add_edge("writer", "reviewer")

    # The real decision: revise or finalise. The dict maps each value the
    # routing function can return to a node, which also lets LangGraph draw it.
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"writer": "writer", "finaliser": "finaliser"},
    )
    graph.add_edge("finaliser", END)
    return graph.compile()


def initial_state(topic: str) -> WorkflowState:
    """Every field starts empty, so each node can safely read any field."""
    return {
        "topic": topic,
        "outline": "",
        "draft": "",
        "feedback": [],
        "scores": {},
        "revision_count": 0,
        "status": "planning",
        "history": [],
        "final": "",
    }
