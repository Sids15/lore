"""Query expansion: generate alternate phrasings for higher retrieval recall.

A single question phrasing can miss relevant chunks. Before the first retrieval
we optionally ask the LLM for a few alternate phrasings / sub-questions; each is
retrieved and the results are fused (RRF) with the original via
``hybrid.retrieve_multi``.

Off by default (one extra LLM call + N extra retrievals per question); enable
with ``LORE_QUERY_EXPANSION_ENABLED=true``. Best-effort: disabled, an LLM error,
or unparseable output all yield ``[]`` so answering proceeds on the original
question alone.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.llm import ollama_client
from app.llm.parsing import parse_json_object

_SYSTEM = (
    "You rewrite a question about a codebase into a few alternative search queries "
    "to improve retrieval. Use synonyms, related terms, and the underlying intent; "
    "keep each query short. Respond with ONLY a JSON object: "
    '{"queries": [<a few alternative phrasings of the question>]}.'
)


async def expand_query(question: str, settings: Settings) -> list[str]:
    """Return alternate phrasings of ``question`` (never raises; ``[]`` on failure)."""
    if not settings.query_expansion_enabled:
        return []
    try:
        raw = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, question, system=_SYSTEM
        )
    except (httpx.HTTPError, ValueError):
        return []

    data = parse_json_object(raw) or {}
    queries = data.get("queries")
    if not isinstance(queries, list):
        return []

    original = question.strip()
    out: list[str] = []
    for item in queries:
        if not isinstance(item, str):
            continue
        phrasing = item.strip()
        if phrasing and phrasing != original and phrasing not in out:
            out.append(phrasing)
        if len(out) >= settings.query_expansion_n:
            break
    return out
