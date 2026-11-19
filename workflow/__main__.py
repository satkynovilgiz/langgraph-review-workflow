"""Command line entry point.

Usage:
    python -m workflow "Explain Kubernetes autoscaling for beginners"
    python -m workflow "..." --out output/my-run      # choose the output folder
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .graph import build_graph, initial_state
from .llm import get_llm, model_name
from .state import MAX_REVISIONS


def print_step(node: str, update: dict) -> None:
    """Print one line (or a few) describing what a node just did."""
    entry = update["history"][-1]
    if node == "planner":
        print("[planner]   outline ready")
    elif node == "writer":
        kind = "revised draft" if entry["is_revision"] else "first draft"
        print(f"[writer]    {kind} (attempt {entry['attempt']}, {entry['word_count']} words)")
    elif node == "reviewer":
        scores = " ".join(f"{k}={v}" for k, v in entry["scores"].items())
        verdict = "PASS" if entry["passed"] else "FAIL"
        print(f"[reviewer]  {scores} -> {verdict}, decision: {entry['decision']}")
        if not entry["passed"]:
            print(f"            rejections so far: {update['revision_count']}/{MAX_REVISIONS}")
            for item in entry["feedback"]:
                print(f"            - {item}")
    elif node == "finaliser":
        print(f"[finaliser] final status: {entry['final_status']}")


def run(topic: str, out_dir: Path, llm=None) -> dict:
    app = build_graph(llm or get_llm())
    state = initial_state(topic)
    print(f"Topic: {topic}\n")

    # stream_mode="updates" yields {node_name: changes} after EACH node runs,
    # which is what lets us print the workflow live, step by step.
    for event in app.stream(state, stream_mode="updates"):
        for node, update in event.items():
            print_step(node, update)
            # Merge the update ourselves to keep the final state.
            for key, value in update.items():
                state[key] = state[key] + value if key == "history" else value

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "final.md").write_text(state["final"] + "\n")
    trace = {
        "topic": topic,
        "model": model_name(),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "final_status": state["status"],
        "rejections": state["revision_count"],
        "max_revisions": MAX_REVISIONS,
        "final_scores": state["scores"],
        "steps": state["history"],
    }
    (out_dir / "trace.json").write_text(json.dumps(trace, indent=2) + "\n")
    print(f"\nSaved {out_dir / 'final.md'} and {out_dir / 'trace.json'}")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan, write and review a beginner explainer.")
    parser.add_argument("topic", help='e.g. "Explain Kubernetes autoscaling for beginners"')
    parser.add_argument("--out", default="output", help="output folder (default: output)")
    args = parser.parse_args()
    run(args.topic, Path(args.out))


if __name__ == "__main__":
    main()
