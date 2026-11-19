"""The four agents (nodes) of the workflow.

Each node is a plain function: it receives the current state and returns a
dict with ONLY the fields it wants to change. LangGraph merges that dict
into the state and moves on to the next node.

`make_nodes(llm)` takes the model as an argument instead of creating it
inside. That lets the tests pass in a FAKE model (no internet, no key).
"""

from . import prompts
from .llm import text_of
from .state import MAX_REVISIONS, PASS_SCORE, Review, WorkflowState


def word_count(text: str) -> int:
    return len(text.split())


def decide(review: Review, revision_count: int) -> tuple[bool, str]:
    """The reviewer's decision rule, kept in plain code so it is predictable.

    Returns (passed, next_status):
      - every score >= 4                -> "approved"
      - failed, rejections < MAX        -> "revising"   (send back to writer)
      - failed, rejections reached MAX  -> "needs_human_review" (stop looping)

    `revision_count` here is the number of rejections INCLUDING this one.
    """
    # We do NOT trust the model's own `passed` flag: we recompute it from
    # the scores, because a model can say "pass" while giving a 3.
    passed = all(score >= PASS_SCORE for score in review.scores.model_dump().values())
    if passed:
        return True, "approved"
    if revision_count >= MAX_REVISIONS:
        return False, "needs_human_review"
    return False, "revising"


def make_nodes(llm):
    """Build the node functions around one chat model."""

    # The reviewer uses "structured output": LangChain asks Gemini to reply
    # in the exact shape of our Pydantic `Review` class and parses it for us.
    reviewer_llm = llm.with_structured_output(Review)

    def planner(state: WorkflowState) -> dict:
        outline = text_of(llm.invoke(prompts.PLANNER.format(topic=state["topic"])))
        return {
            "outline": outline,
            "status": "writing",
            "history": [{"node": "planner", "outline": outline}],
        }

    def writer(state: WorkflowState) -> dict:
        # First pass: write from the outline. Later passes: fix the reviewer's feedback.
        is_revision = state["revision_count"] > 0
        if is_revision:
            prompt = prompts.REVISER.format(
                topic=state["topic"],
                draft=state["draft"],
                feedback="\n".join(f"- {item}" for item in state["feedback"]),
            )
        else:
            prompt = prompts.WRITER.format(topic=state["topic"], outline=state["outline"])
        draft = text_of(llm.invoke(prompt))
        return {
            "draft": draft,
            "history": [{
                "node": "writer",
                "attempt": state["revision_count"] + 1,
                "is_revision": is_revision,
                "word_count": word_count(draft),
                "draft": draft,
            }],
        }

    def reviewer(state: WorkflowState) -> dict:
        review: Review = reviewer_llm.invoke(
            prompts.REVIEWER.format(topic=state["topic"], draft=state["draft"])
        )
        rejections = state["revision_count"]
        passed, status = decide(review, rejections + 1)
        if not passed:
            rejections += 1
        scores = review.scores.model_dump()
        return {
            "scores": scores,
            "feedback": review.feedback,
            "revision_count": rejections,
            "status": status,
            "history": [{
                "node": "reviewer",
                "scores": scores,
                "model_said_passed": review.passed,  # kept to spot disagreements
                "passed": passed,
                "decision": status,
                "feedback": review.feedback,
                "draft_word_count": word_count(state["draft"]),
            }],
        }

    def finaliser(state: WorkflowState) -> dict:
        # No LLM here: assembling the output is deterministic and free.
        final = state["draft"]
        if state["status"] == "needs_human_review":
            notes = "\n".join(f"- {item}" for item in state["feedback"])
            scores = ", ".join(f"{k}: {v}" for k, v in state["scores"].items())
            final = (
                "> **STATUS: NEEDS HUMAN REVIEW**\n"
                f"> The reviewer rejected this draft {state['revision_count']} times "
                f"(limit {MAX_REVISIONS}).\n\n"
                f"{final}\n\n---\n\n## Reviewer's notes\n\n"
                f"Last scores: {scores}\n\n{notes}\n"
            )
        return {
            "final": final,
            "history": [{"node": "finaliser", "final_status": state["status"]}],
        }

    return {"planner": planner, "writer": writer, "reviewer": reviewer, "finaliser": finaliser}
