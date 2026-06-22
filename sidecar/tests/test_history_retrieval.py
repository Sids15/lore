"""Tests for history retrieval and the historical route in context assembly."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.history.retrieval import CommitHit
from app.query import context
from app.query.router import RouteDecision


def _hit(sha: str, summary: str) -> CommitHit:
    return CommitHit(
        sha=sha,
        author="Alice",
        committed_at="2026-01-01T00:00:00",
        message="msg",
        summary=summary,
        files="m.py",
        score=1.0,
    )


def test_historical_route_gathers_commits(monkeypatch):
    async def fake_search(question, *, k=None, settings=None):
        return [_hit("abc1234", "added retry logic")]

    # Historical questions don't need code chunks for this test.
    async def fake_retrieve(question, *, k=None, settings=None):
        return []

    monkeypatch.setattr(context.history_retrieval, "search_history", fake_search)
    monkeypatch.setattr(context.hybrid, "retrieve", fake_retrieve)

    bundle = asyncio.run(
        context.gather("what changed recently?", RouteDecision(categories=["historical"]), Settings())
    )
    assert len(bundle.commits) == 1
    assert bundle.commits[0].sha == "abc1234"


def test_non_historical_route_skips_history(monkeypatch):
    async def fail_search(*args, **kwargs):
        raise AssertionError("history search should not run for non-historical routes")

    async def fake_retrieve(question, *, k=None, settings=None):
        return []

    monkeypatch.setattr(context.history_retrieval, "search_history", fail_search)
    monkeypatch.setattr(context.hybrid, "retrieve", fake_retrieve)

    bundle = asyncio.run(
        context.gather("where is x?", RouteDecision(categories=["code"]), Settings())
    )
    assert bundle.commits == []


def test_format_context_includes_history_section():
    bundle = context.RetrievalBundle(chunks=[], commits=[_hit("abc1234", "added retry logic")])
    text = context.format_context(bundle)
    assert "Recent history" in text
    assert "abc1234" in text
    assert "added retry logic" in text
