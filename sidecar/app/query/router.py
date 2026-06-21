"""Agentic router — classify a question to steer retrieval (PRD §7.5).

A local LLM labels each question with one or more categories so the query layer
can pick the right tools:

* ``code``         — find/explain a specific piece of code (vector + keyword).
* ``relational``   — calls/callers/uses (semantic graph neighbours).
* ``architectural``— dependencies, cycles, layering (static graph + analysis).
* ``historical``   — git history / authorship (served in a later phase).
* ``trivial``      — greetings/meta; no retrieval needed.

Classification is best-effort: any failure (router disabled, LLM error, bad
JSON, empty result) falls back to ``["code"]`` so answering always proceeds.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.llm import ollama_client
from app.llm.parsing import parse_json_object

VALID_CATEGORIES = {"code", "relational", "architectural", "historical", "trivial"}
_DEFAULT = ["code"]

_SYSTEM = (
    "You are a query router for a codebase assistant. Classify the user's question "
    "into one or more categories and respond with ONLY a JSON object: "
    '{"categories": [<one or more of "code","relational","architectural",'
    '"historical","trivial">], "reasoning": "<one short sentence>"}. '
    "Use 'code' to find/explain specific code; 'relational' for what calls/uses what; "
    "'architectural' for dependencies, cycles, or layering; 'historical' for git "
    "history/authorship; 'trivial' for greetings or meta questions needing no code."
)


class RouteDecision(BaseModel):
    """The router's classification of a question."""

    categories: list[str] = []
    reasoning: str = ""

    @property
    def trivial(self) -> bool:
        return self.categories == ["trivial"]

    def needs_graph(self) -> bool:
        return any(c in ("relational", "architectural") for c in self.categories)


def _clean(categories: object) -> list[str]:
    if not isinstance(categories, list):
        return []
    cleaned = [c for c in categories if isinstance(c, str) and c in VALID_CATEGORIES]
    # "trivial" only makes sense alone.
    if "trivial" in cleaned and len(cleaned) > 1:
        cleaned = [c for c in cleaned if c != "trivial"]
    return cleaned


async def classify(question: str, settings: Settings) -> RouteDecision:
    """Classify a question. Never raises — falls back to ``["code"]``."""
    if not settings.router_enabled:
        return RouteDecision(categories=list(_DEFAULT), reasoning="router disabled")
    try:
        raw = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, question, system=_SYSTEM
        )
    except (httpx.HTTPError, ValueError):
        return RouteDecision(categories=list(_DEFAULT), reasoning="router unavailable")

    data = parse_json_object(raw) or {}
    categories = _clean(data.get("categories")) or list(_DEFAULT)
    return RouteDecision(categories=categories, reasoning=str(data.get("reasoning") or ""))
