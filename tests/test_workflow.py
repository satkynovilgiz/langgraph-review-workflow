"""Tests that run the REAL graph with a FAKE model (no internet, no API key).

The fake model returns scripted answers, so we can force each path:
approve first time, revise once then approve, and reject twice.
"""

import json
from typing import get_type_hints

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from workflow.__main__ import run
from workflow.nodes import length_check
from workflow.graph import build_graph, initial_state, route_after_review
from workflow.state import MAX_REVISIONS, ChecklistScores, Review, WorkflowState

GOOD = {"accuracy": 5, "clarity": 5, "structure": 4, "length": 5, "example": 5}
BAD = {"accuracy": 4, "clarity": 3, "structure": 4, "length": 2, "example": 4}


def review(scores: dict, feedback: list[str] | None = None) -> Review:
    return Review(scores=ChecklistScores(**scores), passed=False, feedback=feedback or [])


class FakeLLM:
    """Stands in for Gemini. Text calls return scripted strings; the
    reviewer's structured calls return scripted Review objects."""

    def __init__(self, reviews: list[Review], draft_words: int = 400):
        self.reviews = list(reviews)
        self.draft_words = draft_words  # length of each fake draft
        self.prompts: list[str] = []
        self.text_calls = 0

    def invoke(self, prompt: str) -> AIMessage:
        self.prompts.append(prompt)
        self.text_calls += 1
        body = " ".join(["word"] * (self.draft_words - 4))
        return AIMessage(content=f"# Title\n\nfake text {self.text_calls} {body}")

    def with_structured_output(self, schema):
        fake = self

        class Structured:
            def invoke(self, prompt):
                fake.prompts.append(prompt)
                return fake.reviews.pop(0)

        return Structured()


def run_graph(reviews: list[Review], draft_words: int = 400) -> tuple[dict, FakeLLM]:
    llm = FakeLLM(reviews, draft_words)
    final_state = build_graph(llm).invoke(initial_state("Explain DNS for beginners"))
    return final_state, llm


def nodes_run(state: dict) -> list[str]:
    return [step["node"] for step in state["history"]]


def test_approve_first_time():
    state, _ = run_graph([review(GOOD)])
    assert state["status"] == "approved"
    assert state["revision_count"] == 0
    assert nodes_run(state) == ["planner", "writer", "reviewer", "finaliser"]
    assert "NEEDS HUMAN REVIEW" not in state["final"]


def test_revise_once_then_approve():
    state, llm = run_graph([review(BAD, ["Add a real example of a DNS lookup."]), review(GOOD)])
    assert state["status"] == "approved"
    assert state["revision_count"] == 1
    assert nodes_run(state) == [
        "planner", "writer", "reviewer", "writer", "reviewer", "finaliser",
    ]
    # The writer's second prompt must contain the reviewer's feedback.
    revise_prompt = llm.prompts[3]
    assert "Add a real example of a DNS lookup." in revise_prompt
    assert state["final"] == state["draft"]  # approved drafts are published as-is


def test_reject_twice_needs_human_review():
    state, _ = run_graph([
        review(BAD, ["Too short."]),
        review(BAD, ["Still too short; explain 'resolver'."]),
    ])
    assert state["status"] == "needs_human_review"
    assert state["revision_count"] == MAX_REVISIONS
    # The loop stopped: the writer ran exactly twice, no third attempt.
    assert nodes_run(state).count("writer") == 2
    assert nodes_run(state)[-1] == "finaliser"
    # The reviewer's notes are attached to the final output.
    assert "NEEDS HUMAN REVIEW" in state["final"]
    assert "explain 'resolver'" in state["final"]


def test_code_overrides_model_pass_flag():
    """The model says passed=True but gave a 3 -> our rule must still reject."""
    sneaky = Review(scores=ChecklistScores(**BAD), passed=True, feedback=["x"])
    state, _ = run_graph([sneaky, review(GOOD)])
    assert state["history"][2]["passed"] is False
    assert state["revision_count"] == 1


def test_state_schema_is_respected():
    expected = {
        "topic", "outline", "draft", "feedback", "scores",
        "revision_count", "status", "history", "final",
    }
    assert set(get_type_hints(WorkflowState)) == expected

    state, _ = run_graph([review(GOOD)])
    assert set(state) == expected  # no stray keys added by any node
    assert isinstance(state["revision_count"], int)
    assert isinstance(state["feedback"], list)
    assert set(state["scores"]) == {"accuracy", "clarity", "structure", "length", "example"}
    assert all(1 <= v <= 5 for v in state["scores"].values())


def test_scores_outside_1_to_5_are_rejected():
    with pytest.raises(ValidationError):
        ChecklistScores(accuracy=6, clarity=5, structure=5, length=5, example=5)


def test_routing_function():
    assert route_after_review({"status": "revising"}) == "writer"
    assert route_after_review({"status": "approved"}) == "finaliser"
    assert route_after_review({"status": "needs_human_review"}) == "finaliser"


def test_cli_run_writes_final_and_trace(tmp_path, capsys):
    run("Explain DNS for beginners", tmp_path, llm=FakeLLM([review(BAD, ["fix"]), review(GOOD)]))
    trace = json.loads((tmp_path / "trace.json").read_text())
    assert trace["final_status"] == "approved"
    assert [s["node"] for s in trace["steps"]].count("reviewer") == 2
    assert (tmp_path / "final.md").read_text().startswith("# Title")
    printed = capsys.readouterr().out
    assert "[reviewer]" in printed and "decision: revising" in printed


def test_length_check_scores_word_counts():
    assert length_check(450) == (5, None)
    assert length_check(300)[0] == 5 and length_check(600)[0] == 5
    score, fix = length_check(611)  # a real draft the LLM reviewer wrongly gave 5
    assert score == 3 and "Cut at least 11 words" in fix
    assert length_check(120)[0] == 1


def test_code_overrides_llm_length_score():
    """LLM says length=5, but the draft is 700 words -> code rejects it."""
    state, _ = run_graph([review(GOOD), review(GOOD)], draft_words=700)
    first_review = state["history"][2]
    assert first_review["model_length_score"] == 5
    assert first_review["scores"]["length"] == 2
    assert first_review["passed"] is False
    assert "the limit is 600. Cut at least" in first_review["feedback"][0]
