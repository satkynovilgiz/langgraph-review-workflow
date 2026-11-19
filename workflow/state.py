"""The shared state that every agent (node) reads from and writes to.

Think of the state as a clipboard passed down an assembly line:
each node reads what it needs, and returns ONLY the fields it changed.
LangGraph merges those changes into the clipboard for the next node.
"""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

# How many times the reviewer may reject a draft before we stop looping.
# After the 2nd rejection the workflow finalises with "needs_human_review".
MAX_REVISIONS = 2

# Every item on the reviewer's checklist must score at least this to pass.
PASS_SCORE = 4

# The possible values of state["status"].
Status = Literal["planning", "writing", "revising", "approved", "needs_human_review"]


class WorkflowState(TypedDict):
    topic: str                 # the user's request, e.g. "Explain Kubernetes autoscaling"
    outline: str               # written by the planner
    draft: str                 # written (and rewritten) by the writer
    feedback: list[str]        # the reviewer's specific notes on the latest draft
    scores: dict[str, int]     # the reviewer's 1-5 score for each checklist item
    revision_count: int        # how many times the reviewer has rejected a draft
    status: Status             # where the workflow is / how it ended
    # history uses a "reducer" (operator.add): when a node returns
    # {"history": [new_entry]}, LangGraph APPENDS it instead of replacing
    # the list. That is how we build a full trace of every step.
    history: Annotated[list[dict], operator.add]
    final: str                 # the finished markdown, built by the finaliser


class ChecklistScores(BaseModel):
    """One 1-5 score per checklist item."""

    accuracy: int = Field(ge=1, le=5, description="Facts are correct, nothing misleading.")
    clarity: int = Field(ge=1, le=5, description="A beginner can follow it; jargon is explained.")
    structure: int = Field(ge=1, le=5, description="Title, intro, logical sections, short conclusion.")
    length: int = Field(ge=1, le=5, description="5 if 300-600 words; lower the further outside.")
    example: int = Field(ge=1, le=5, description="Includes at least one concrete, realistic example.")


class Review(BaseModel):
    """The STRUCTURED output the reviewer must return (not just 'looks good')."""

    scores: ChecklistScores
    passed: bool = Field(description="True only if every score is 4 or higher.")
    feedback: list[str] = Field(
        description="Specific, actionable fixes. Empty list if nothing needs changing."
    )
