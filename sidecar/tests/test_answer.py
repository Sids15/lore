"""Tests for grounded question answering (no network: retrieve + generate mocked)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.query import answer
from app.query.answer import answer_question
from app.retrieval.hybrid import RetrievedChunk


def _chunk(symbol: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=symbol,
        repo="r",
        file_path=f"{symbol}.py",
        language="python",
        kind="function",
        symbol=symbol,
        qualified_name=f"{symbol}.py::{symbol}",
        start_line=1,
        end_line=3,
        code=f"def {symbol}(): ...",
        score=1.0,
    )


def _patch_retrieve(monkeypatch, chunks):
    async def fake_retrieve(question, *, k=None, settings=None):
        return chunks

    monkeypatch.setattr(answer.hybrid, "retrieve", fake_retrieve)


def _patch_generate(monkeypatch, *, answer_text, grounding_json):
    calls: list[str | None] = []

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        calls.append(system)
        if system and "verify" in system.lower():
            return grounding_json
        return answer_text

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)
    return calls


def test_answer_with_grounding(monkeypatch):
    _patch_retrieve(monkeypatch, [_chunk("retry"), _chunk("backoff")])
    calls = _patch_generate(
        monkeypatch,
        answer_text="The retry logic is in retry.py [retry.py:1].",
        grounding_json='{"grounded": true, "unsupported": []}',
    )

    resp = asyncio.run(answer_question("where is retry?", settings=Settings()))

    assert "retry" in resp.answer.lower()
    assert resp.grounded is True
    assert [c.symbol for c in resp.sources] == ["retry", "backoff"]
    assert len(calls) == 2  # answer + grounding pass


def test_ungrounded_answer_is_flagged(monkeypatch):
    _patch_retrieve(monkeypatch, [_chunk("retry")])
    _patch_generate(
        monkeypatch,
        answer_text="It uses a circuit breaker.",
        grounding_json='{"grounded": false, "unsupported": ["circuit breaker claim"]}',
    )

    resp = asyncio.run(answer_question("how does it work?", settings=Settings()))

    assert resp.grounded is False
    assert resp.unsupported == ["circuit breaker claim"]


def test_grounding_disabled_skips_second_pass(monkeypatch):
    _patch_retrieve(monkeypatch, [_chunk("retry")])
    calls = _patch_generate(
        monkeypatch, answer_text="An answer.", grounding_json="unused"
    )

    resp = asyncio.run(
        answer_question("q", settings=Settings(grounding_enabled=False))
    )

    assert resp.grounded is True
    assert len(calls) == 1  # only the answer generation, no grounding pass


def test_no_context_returns_fallback(monkeypatch):
    _patch_retrieve(monkeypatch, [])

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("generate should not be called without context")

    monkeypatch.setattr(answer.ollama_client, "generate", unexpected_generate)

    resp = asyncio.run(answer_question("anything?", settings=Settings()))

    assert resp.sources == []
    assert resp.grounded is True
    assert "indexed" in resp.answer.lower()


def test_unparseable_grounding_fails_open(monkeypatch):
    _patch_retrieve(monkeypatch, [_chunk("retry")])
    _patch_generate(
        monkeypatch,
        answer_text="An answer.",
        grounding_json="not json at all",
    )

    resp = asyncio.run(answer_question("q", settings=Settings()))

    assert resp.grounded is True  # fail open when the check can't be parsed
    assert resp.unsupported == []
