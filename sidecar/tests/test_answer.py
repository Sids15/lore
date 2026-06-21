"""Tests for grounded question answering (no network: gather + generate mocked)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.query import answer
from app.query.context import RetrievalBundle
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


def _settings() -> Settings:
    # Disable the router so no LLM call is needed to classify; route -> ["code"].
    return Settings(router_enabled=False)


def _patch_gather(monkeypatch, chunks, *, graph_notes=None, graph_used=False):
    async def fake_gather(question, route, settings, *, broaden=False, k=None):
        return RetrievalBundle(
            chunks=chunks, graph_notes=graph_notes or [], graph_used=graph_used
        )

    monkeypatch.setattr(answer.context, "gather", fake_gather)


def _patch_generate(monkeypatch, *, answer_text, grounding_json):
    calls: list[str | None] = []

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        calls.append(system)
        if system and "verify" in system.lower():
            return grounding_json
        return answer_text

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)
    return calls


def test_answer_with_grounding_and_categories(monkeypatch):
    _patch_gather(monkeypatch, [_chunk("retry"), _chunk("backoff")], graph_used=True)
    _patch_generate(
        monkeypatch,
        answer_text="The retry logic is in retry.py [retry.py:1].",
        grounding_json='{"grounded": true, "unsupported": []}',
    )

    resp = asyncio.run(answer.answer_question("where is retry?", settings=_settings()))

    assert "retry" in resp.answer.lower()
    assert resp.grounded is True
    assert resp.categories == ["code"]
    assert resp.graph_used is True
    assert [c.symbol for c in resp.sources] == ["retry", "backoff"]


def test_ungrounded_answer_is_flagged(monkeypatch):
    _patch_gather(monkeypatch, [_chunk("retry")])
    _patch_generate(
        monkeypatch,
        answer_text="It uses a circuit breaker.",
        grounding_json='{"grounded": false, "unsupported": ["circuit breaker claim"]}',
    )

    resp = asyncio.run(
        answer.answer_question(
            "how?", settings=Settings(router_enabled=False, self_correct_enabled=False)
        )
    )
    assert resp.grounded is False
    assert resp.unsupported == ["circuit breaker claim"]
    assert resp.corrected is False  # self-correction disabled -> no retry


def test_self_correction_retries_when_ungrounded(monkeypatch):
    async def fake_gather(question, route, settings, *, broaden=False, k=None):
        # The broadened (retry) pass adds graph context.
        notes = ["x calls y"] if broaden else []
        return RetrievalBundle(chunks=[_chunk("a")], graph_notes=notes, graph_used=broaden)

    monkeypatch.setattr(answer.context, "gather", fake_gather)

    state = {"answers": 0}

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        if system and "verify" in system.lower():
            # Ground only the second answer.
            return '{"grounded": true}' if state["answers"] >= 2 else '{"grounded": false}'
        state["answers"] += 1
        return f"answer {state['answers']}"

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)

    resp = asyncio.run(
        answer.answer_question(
            "q", settings=Settings(router_enabled=False, self_correct_enabled=True)
        )
    )
    assert resp.corrected is True
    assert resp.grounded is True
    assert resp.graph_used is True  # the broadened retry pulled in graph context


def test_no_retry_when_already_grounded(monkeypatch):
    _patch_gather(monkeypatch, [_chunk("a")])
    calls = _patch_generate(
        monkeypatch, answer_text="grounded answer", grounding_json='{"grounded": true}'
    )

    resp = asyncio.run(
        answer.answer_question(
            "q", settings=Settings(router_enabled=False, self_correct_enabled=True)
        )
    )
    assert resp.grounded is True
    assert resp.corrected is False
    assert len(calls) == 2  # answer + grounding only; no retry pass


def test_no_context_returns_fallback(monkeypatch):
    _patch_gather(monkeypatch, [])

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("generate should not be called without context")

    monkeypatch.setattr(answer.ollama_client, "generate", unexpected_generate)

    resp = asyncio.run(answer.answer_question("anything?", settings=_settings()))
    assert resp.sources == []
    assert resp.grounded is True
    assert "indexed" in resp.answer.lower()
