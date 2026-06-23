"""Tests for streamed question answering (no network: gather + LLM mocked)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.query import answer
from app.query.context import RetrievalBundle
from app.query.router import RouteDecision
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


def _patch_gather(monkeypatch, bundle_factory):
    async def fake_gather(question, route, settings, *, broaden=False, k=None):
        return bundle_factory(broaden)

    monkeypatch.setattr(answer.context, "gather", fake_gather)


def _patch_stream(monkeypatch, tokens):
    async def fake_stream(base_url, model, prompt, *, system=None, **kwargs):
        for token in tokens:
            yield token

    monkeypatch.setattr(answer.ollama_client, "generate_stream", fake_stream)


def _patch_grounding(monkeypatch, grounding_json):
    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        return grounding_json

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)


def _collect(question, settings) -> list[dict]:
    async def run() -> list[dict]:
        return [event async for event in answer.answer_question_stream(question, settings=settings)]

    return asyncio.run(run())


def _tokens(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "token")


def test_stream_emits_meta_tokens_and_final(monkeypatch):
    _patch_gather(monkeypatch, lambda broaden: RetrievalBundle(chunks=[_chunk("a")], graph_used=True))
    _patch_stream(monkeypatch, ["Hello", " world"])
    _patch_grounding(monkeypatch, '{"grounded": true, "unsupported": []}')

    events = _collect("where is a?", Settings(router_enabled=False, self_correct_enabled=False))

    assert events[0]["type"] == "meta"
    assert events[0]["categories"] == ["code"]
    assert events[0]["graph_used"] is True
    assert [s["symbol"] for s in events[0]["sources"]] == ["a"]

    assert _tokens(events) == "Hello world"

    final = events[-1]
    assert final["type"] == "final"
    assert final["grounded"] is True
    assert final["corrected"] is False


def test_stream_trivial_skips_retrieval(monkeypatch):
    async def fake_classify(question, settings):
        return RouteDecision(categories=["trivial"])

    monkeypatch.setattr(answer.router, "classify", fake_classify)

    async def fail_gather(*args, **kwargs):
        raise AssertionError("gather should not run for a trivial question")

    monkeypatch.setattr(answer.context, "gather", fail_gather)
    _patch_stream(monkeypatch, ["hi ", "there"])

    events = _collect("hello", Settings())

    assert events[0]["type"] == "meta"
    assert events[0]["sources"] == []
    assert _tokens(events) == "hi there"
    assert events[-1] == {"type": "final", "grounded": True, "unsupported": [], "corrected": False}


def test_stream_no_context_returns_fallback(monkeypatch):
    _patch_gather(monkeypatch, lambda broaden: RetrievalBundle(chunks=[]))

    async def fail_stream(*args, **kwargs):
        raise AssertionError("generation should not run without context")
        yield  # pragma: no cover - make this an async generator

    monkeypatch.setattr(answer.ollama_client, "generate_stream", fail_stream)

    events = _collect(
        "anything?", Settings(router_enabled=False, self_correct_enabled=False)
    )

    assert events[0]["type"] == "meta"
    assert "indexed" in _tokens(events).lower()
    assert events[-1]["type"] == "final"
    assert events[-1]["grounded"] is True


def test_stream_self_corrects_when_ungrounded(monkeypatch):
    _patch_gather(
        monkeypatch,
        lambda broaden: RetrievalBundle(
            chunks=[_chunk("a")],
            graph_notes=["x calls y"] if broaden else [],
            graph_used=broaden,
        ),
    )
    _patch_stream(monkeypatch, ["draft"])

    state = {"checks": 0}

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        state["checks"] += 1
        # Ground only the second (broadened) pass.
        return '{"grounded": true}' if state["checks"] >= 2 else '{"grounded": false}'

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)

    events = _collect("q", Settings(router_enabled=False, self_correct_enabled=True))

    assert any(e["type"] == "replace" for e in events)
    final = events[-1]
    assert final["type"] == "final"
    assert final["corrected"] is True
    assert final["grounded"] is True
