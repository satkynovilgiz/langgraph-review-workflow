# langgraph-review-workflow

A multi-agent workflow built with **LangGraph** and **Google Gemini**. It turns a short topic into a
beginner-friendly technical explainer, like a short blog post.

The work is split across four specialised agents that hand work to each other. One of them is a
**reviewer that can send the work back**:

| Agent | Job | Uses the LLM? |
|---|---|---|
| **planner** | Turns the topic into an outline | yes |
| **writer** | Writes the draft, or revises it using the reviewer's feedback | yes |
| **reviewer** | Scores the draft against a written checklist, then approves it or sends it back | yes (structured output) |
| **finaliser** | Builds the final markdown and adds reviewer notes if a human must step in | no (plain code) |

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your real GOOGLE_API_KEY in .env (it is git-ignored)

python -m workflow "Explain Kubernetes autoscaling for beginners"
pytest                         # runs with a fake LLM: no internet or key needed
```

Optional: set `GEMINI_MODEL=...` in `.env` to use a different model. The default is
`gemini-3.5-flash-lite`.

Each run prints every step live and saves:
- `output/final.md`: the finished explainer
- `output/trace.json`: every node that ran, every score, decision and draft revision

## The graph

Exported from LangGraph itself (`python scripts/export_diagram.py`). A PNG copy is in
[`docs/graph.png`](docs/graph.png). **Dotted arrows are conditional edges**: the reviewer decides
which way to go.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	planner(planner)
	writer(writer)
	reviewer(reviewer)
	finaliser(finaliser)
	__end__([<p>__end__</p>]):::last
	__start__ --> planner;
	planner --> writer;
	reviewer -.-> finaliser;
	reviewer -.-> writer;
	writer --> reviewer;
	finaliser --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

![Workflow graph](docs/graph.png)

## The state schema

All agents share one state object, a `TypedDict` in [`workflow/state.py`](workflow/state.py).
Each node returns **only the fields it changed**, and LangGraph merges them in.

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `topic` | `str` | user | The request, e.g. "Explain Kubernetes autoscaling for beginners" |
| `outline` | `str` | planner | Title plus 4–6 sections, one of them a concrete example |
| `draft` | `str` | writer | The current version of the article |
| `feedback` | `list[str]` | reviewer | Specific fixes for the latest draft |
| `scores` | `dict[str, int]` | reviewer | 1–5 per checklist item |
| `revision_count` | `int` | reviewer | How many times the reviewer has **rejected** a draft |
| `status` | `"planning" \| "writing" \| "revising" \| "approved" \| "needs_human_review"` | planner, reviewer | Where the workflow is, and how it ended |
| `history` | `list[dict]` (append-only) | every node | The trace. It uses a reducer (`operator.add`), so new entries are **appended**, not overwritten |
| `final` | `str` | finaliser | The finished markdown |

## How the reviewer decides

The reviewer gets a written checklist (in [`workflow/prompts.py`](workflow/prompts.py)) and must
reply in a fixed shape, the Pydantic `Review` model. It cannot just say "looks good":

```python
class ChecklistScores(BaseModel):
    accuracy: int    # 1-5: facts correct, nothing misleading
    clarity: int     # 1-5: a beginner can follow it, jargon explained
    structure: int   # 1-5: title, intro, logical sections, conclusion
    length: int      # 1-5: 5 if 300-600 words
    example: int     # 1-5: has a concrete, realistic example

class Review(BaseModel):
    scores: ChecklistScores
    passed: bool
    feedback: list[str]   # specific, actionable fixes
```

`llm.with_structured_output(Review)` makes Gemini answer in this shape, and LangChain parses it into
a Python object.

**The approve rule lives in code, not in the LLM.** The draft is approved only if **every score is
4 or higher**. The code recalculates this from the scores (`decide()` in
[`workflow/nodes.py`](workflow/nodes.py)) and ignores the model's own `passed` flag, because a
model can say "pass" while also giving a 3. Both values are saved in the trace, so you can see
when they disagree.

**The `length` score is also set by code.** The code counts the words and overrides whatever the
LLM guessed, because real runs showed it can't count (see "The failure mode I found").

The conditional edge (`route_after_review` in [`workflow/graph.py`](workflow/graph.py)) then picks
the next node:

| Reviewer result | `status` | Next node |
|---|---|---|
| every score ≥ 4 | `approved` | finaliser |
| some score < 4, fewer than 2 rejections so far | `revising` | **writer**, with the feedback |
| some score < 4, this is the 2nd rejection | `needs_human_review` | finaliser |

## What happens when the reviewer rejects twice

`MAX_REVISIONS = 2` (in `workflow/state.py`). Without a limit, a strict reviewer and a stubborn
writer could loop forever and burn API calls. Step by step:

1. Writer writes draft 1. Reviewer **rejects** it, so `revision_count = 1` and it goes back to the writer with feedback.
2. Writer revises into draft 2, fixing the feedback. Reviewer **rejects again**, so `revision_count = 2`, which hits the limit.
3. The reviewer sets `status = "needs_human_review"` and the conditional edge routes to the **finaliser**, not the writer. **The loop stops.**
4. The finaliser still produces `final.md`, but puts a clear banner on top and adds the reviewer's last scores and notes at the bottom:

```markdown
> **STATUS: NEEDS HUMAN REVIEW**
> The reviewer rejected this draft 2 times (limit 2).

...the last draft...

## Reviewer's notes
Last scores: accuracy: 4, clarity: 3, ...
- <the reviewer's specific feedback>
```

So the writer runs **at most twice**, and the worst case is 5 LLM calls (planner, writer, reviewer,
writer, reviewer). A person gets the best draft plus a list of exactly what is still wrong, instead
of the workflow either looping forever or quietly publishing a draft that failed review.

Every LLM call also has a **60-second timeout and at most 2 retries**
([`workflow/llm.py`](workflow/llm.py)), so a busy model can't hang the workflow either.

## Tests

`pytest` runs the **real graph** with a **fake LLM** that returns scripted answers. No internet or
API key is needed.

| Test | Checks |
|---|---|
| `test_approve_first_time` | planner → writer → reviewer → finaliser, status `approved` |
| `test_revise_once_then_approve` | one loop back to the writer, and the writer's prompt contains the feedback |
| `test_reject_twice_needs_human_review` | stops after 2 rejections, writer ran exactly twice, notes in the output |
| `test_code_overrides_model_pass_flag` | model says `passed=True` with a 3, and the code still rejects |
| `test_state_schema_is_respected` | final state has exactly the schema's fields, with the right types |
| `test_scores_outside_1_to_5_are_rejected` | a score of 6 fails validation |
| `test_routing_function` | the conditional edge maps each status to the right node |
| `test_cli_run_writes_final_and_trace` | the CLI prints steps and writes both output files |
| `test_length_check_scores_word_counts` | 300–600 words scores 5; 611 words scores 3 with "Cut at least 11 words" |
| `test_code_overrides_llm_length_score` | LLM says length=5 for a 700-word draft, and the code rejects it |

## Example runs

Both runs are **real, unedited output** from `gemini-3.5-flash-lite` on 2026-11-18, after the
length fix described below.

### Example 1: "Explain Kubernetes autoscaling for beginners"

Full output is committed in [`output/example/`](output/example/): `final.md`, `trace.json` and
`console.txt`.

```
$ python -m workflow "Explain Kubernetes autoscaling for beginners"
Topic: Explain Kubernetes autoscaling for beginners

[planner]   outline ready
[writer]    first draft (attempt 1, 524 words)
[reviewer]  accuracy=5 clarity=5 structure=5 length=5 example=5 -> PASS, decision: approved
[finaliser] final status: approved
```

The planner's outline had 5 sections, including "Concrete Example: The Black Friday Sale Shop".
The final article starts:

> # Kubernetes Autoscaling Explained for Beginners
> ## What is Kubernetes Autoscaling?
> Imagine running an online store where traffic constantly changes. Kubernetes autoscaling is a
> feature that automatically adjusts your computing resources—like processing power and memory—based
> on how much demand your application is currently experiencing. …

### Example 2: "Explain step by step what happens when you type a URL into a browser and press Enter, covering DNS, TCP, TLS, HTTP and rendering, for beginners"

```
[planner]   outline ready
[writer]    first draft (attempt 1, 518 words)
[reviewer]  accuracy=5 clarity=5 structure=5 length=5 example=5 -> PASS, decision: approved
[finaliser] final status: approved
```

The article starts with:

> # Title: What Happens When You Press Enter? A Beginner's Guide to the Web

Note the literal **"Title:"** in the heading. The planner's outline label leaked into the article,
and the reviewer still gave `structure=5`. That is part of the failure mode below. Trace:
[`docs/evidence/url-title-leak-trace.json`](docs/evidence/url-title-leak-trace.json).

### What about the revise and reject-twice paths?

In all of my real runs the reviewer approved the first draft, so **the revise loop never ran with
the real model**. I am not going to invent output for it. The paths are covered two ways:
- **Tests**: `test_revise_once_then_approve` and `test_reject_twice_needs_human_review` run the
  real graph with a fake LLM.
- **A real reviewer rejection**: [`scripts/probe_reviewer.py`](scripts/probe_reviewer.py) sends the
  real reviewer a deliberately bad HTTPS draft (it contains a false fact and unexplained jargon, and
  has no example). The real Gemini reply
  ([`docs/evidence/reviewer-probe-output.json`](docs/evidence/reviewer-probe-output.json)) was
  `accuracy=2 clarity=1 structure=4 length=5 example=1 -> decision: revising`, with feedback such as
  *"correct the false claim that the server sends its private key to the browser, as servers never
  transmit their private keys."*

## The failure mode I found

**Run log:** 7 topics before the fix (Kubernetes autoscaling, DNS, public-key cryptography, Git
rebase vs merge, vector databases, CAP theorem, HTTPS), the same 7 again after the fix, plus the
"type a URL" topic. That makes 15 completed real reviews.

### The problem: the reviewer was a rubber stamp

**Every one of the 15 real reviews scored 5/5/5/5/5 with an empty feedback list.** The scores never
varied, so the reviewer was not telling drafts apart. Two cases show this is a real bug and not
just "the drafts were perfect":

1. **It could not count words.** Before the fix, the DNS draft was **605 words** and the CAP
   theorem draft was **611 words**. Both break the 300–600 rule, and both got `length=5` and were
   approved. Traces:
   [`dns-605-words-trace.json`](docs/evidence/before-fix/dns-605-words-trace.json),
   [`cap-611-words-trace.json`](docs/evidence/before-fix/cap-611-words-trace.json).
2. **It missed a visible formatting bug.** The "type a URL" article's heading is
   `# Title: What Happens…`, and it still got `structure=5`.

To check that the reviewer wasn't simply broken, I gave it a deliberately bad draft (see above).
It did reject that draft with good, specific feedback. So the honest conclusion is: **the reviewer
catches clearly broken drafts, but it can't grade a decent one.** It gives 5 to anything
reasonable, and it can't measure things like word count.

One likely reason is that the same model writes **and** reviews, and a model tends to like text
that sounds like its own writing.

### How I fixed it

- **Objective checks moved into code.** `length_check()` in [`workflow/nodes.py`](workflow/nodes.py)
  counts the words and **overrides** the LLM's length score. If the draft is out of range, it adds
  exact feedback such as *"The draft is 611 words; the limit is 600. Cut at least 11 words."* The
  LLM's own guess is still saved as `model_length_score` in the trace, so you can see when it was
  wrong. Test: `test_code_overrides_llm_length_score`. This fully fixes the word-count part.
- **The reviewer is told the word count** and given a clear meaning for each score (5 = "you
  looked for problems and found none").
- **I also tried a stricter prompt.** It did not help on its own: the 7 runs after the fix
  still all scored 5s. I'm reporting that honestly rather than claiming the prompt fixed it.

### What I would do next

- **Move more checks into code**: for example, the title must start with `# ` and must not contain
  "Title:", and there must be at least 3 `##` sections. Anything a rule can check, the LLM
  shouldn't be guessing.
- **Use a different, stronger model for the reviewer** (e.g. a separate `GEMINI_REVIEWER_MODEL`),
  so the writer isn't marking its own homework.
- **Ask for evidence before the score**: make the reviewer quote one weak sentence per checklist
  item before scoring it, which pushes it to actually look.
- **Keep `scripts/probe_reviewer.py` as a regression check**: a reviewer that stops rejecting the
  known-bad draft is broken.

**Side note (a second, smaller problem):** when I first ran 6 topics in parallel, one crashed with
`429 RESOURCE_EXHAUSTED`. The free tier allows 15 requests per minute for this model, and each run
makes 3–5 calls. The 2-retry cap correctly stopped it from hanging, but it cannot wait out a
per-minute quota. So run topics one at a time, or add a pause between runs.

## Project layout

```
workflow/
  state.py      state schema, Review model, MAX_REVISIONS
  llm.py        Gemini model with timeout + retry cap
  prompts.py    each agent's instructions, including the reviewer checklist
  nodes.py      planner, writer, reviewer, finaliser + the decide() rule
  graph.py      wires nodes together, including the conditional edge
  __main__.py   CLI: live step printing, saves final.md + trace.json
tests/          fake-LLM tests
scripts/        diagram export, reviewer probe, API-key check (install as a pre-commit hook:
                cp scripts/check_no_keys.sh .git/hooks/pre-commit)
docs/           graph.png, graph.mmd, evidence/ (real traces used in the failure-mode section)
output/example/ one committed example run
```
