"""On-demand LLM refactor proposals for a single candidate.

Grounds the proposal in the candidate's actual code (via hybrid retrieval) so the
suggestion references real symbols. Best-effort: any LLM/retrieval failure returns
a short fallback rather than raising, so the UI always gets a response.
"""

from __future__ import annotations

import httpx

from app.config import Settings, get_settings
from app.llm import ollama_client
from app.refactor.candidates import RefactorCandidate
from app.retrieval import hybrid

_SYSTEM = (
    "You are a refactoring assistant for a codebase. Given a structural problem and "
    "the relevant code, propose a concrete, safe refactor: numbered steps, which files "
    "and functions to change, and the main risks. Be specific and concise. Do not invent "
    "code or APIs that are not shown in the context."
)

_FALLBACK = (
    "Couldn't generate a suggestion right now (the local LLM may be unavailable). "
    "The structural issue still stands — see the summary above."
)


def _short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


async def suggest_refactor(candidate: RefactorCandidate, settings: Settings | None = None) -> str:
    """Return a grounded refactor proposal for a candidate. Never raises."""
    settings = settings or get_settings()

    query = f"{candidate.title} {' '.join(_short(f) for f in candidate.files)}"
    try:
        chunks = await hybrid.retrieve(query, settings=settings)
    except (httpx.HTTPError, ValueError):
        chunks = []

    blocks = [
        f"[{c.file_path}:{c.start_line}-{c.end_line}] ({c.kind} {c.symbol})\n{c.code}"
        for c in chunks
    ]
    context_text = "\n\n".join(blocks) if blocks else "(no code retrieved)"

    prompt = (
        f"Problem ({candidate.kind}): {candidate.title}\n{candidate.summary}\n\n"
        f"Involved files: {', '.join(candidate.files)}\n\n"
        f"Relevant code:\n{context_text}\n\n"
        "Propose a refactor:"
    )
    try:
        return await ollama_client.generate(
            settings.ollama_url, settings.generation_model, prompt, system=_SYSTEM
        )
    except (httpx.HTTPError, ValueError):
        return _FALLBACK
