"""Creates the Gemini chat model used by every agent.

All LLM settings live here so there is exactly one place to change them.
"""

import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # fast and cheap; override with GEMINI_MODEL in .env
TIMEOUT_SECONDS = 60                     # give up on a single call after 60 s
MAX_RETRIES = 2                          # retry a failed/slow call at most twice


def model_name() -> str:
    load_dotenv()
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def get_llm() -> ChatGoogleGenerativeAI:
    """Return a Gemini model with a hard timeout and retry cap.

    The cap means a busy or overloaded model can't hang the workflow:
    the worst case is (1 try + 2 retries) x 60 s, and then we get an error.
    """
    load_dotenv()  # reads GOOGLE_API_KEY (and optional GEMINI_MODEL) from .env
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and put your key in it."
        )
    return ChatGoogleGenerativeAI(
        model=model_name(),
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        temperature=0.4,
    )


def text_of(message) -> str:
    """Get plain text from a model reply.

    Newer Gemini replies can be a list of 'content blocks' instead of a
    plain string, so we handle both shapes.
    """
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
    return "".join(parts).strip()
