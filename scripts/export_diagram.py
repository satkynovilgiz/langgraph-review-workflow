"""Export LangGraph's own diagram of the workflow.

Writes docs/graph.mmd (mermaid text, pasted into the README) and
docs/graph.png (rendered via the mermaid.ink web API, so it needs internet).
No API key is needed: we only build the graph, we never call the model.

Run:  python scripts/export_diagram.py
"""

from pathlib import Path

from workflow.graph import build_graph


class _NoModel:
    """Placeholder model: drawing the graph never calls it."""

    def with_structured_output(self, schema):
        return self


def main() -> None:
    docs = Path("docs")
    docs.mkdir(exist_ok=True)
    drawable = build_graph(_NoModel()).get_graph()

    (docs / "graph.mmd").write_text(drawable.draw_mermaid())
    print("wrote docs/graph.mmd")

    (docs / "graph.png").write_bytes(drawable.draw_mermaid_png())
    print("wrote docs/graph.png")


if __name__ == "__main__":
    main()
