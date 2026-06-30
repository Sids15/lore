"""Tests for streamed question answering (no network: gather + LLM mocked)."""

from __future__ import annotations

import asyncio

import httpx

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
    async def fake_gather(question, route, settings, *, broaden=False, k=None, extra_queries=None):
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


def _ground_on_check(state, threshold):
    """A fake `generate`: a grounded/ungrounded verdict on the Nth verify call,
    a fixed answer otherwise (retries are non-streamed via _answer_from_bundle)."""

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        if system and "verify" in system.lower():
            state["grounds"] += 1
            return '{"grounded": true}' if state["grounds"] >= threshold else '{"grounded": false}'
        return "refined answer"

    return fake_generate


def test_stream_self_corrects_when_ungrounded(monkeypatch):
    _patch_gather(monkeypatch, lambda broaden: RetrievalBundle(chunks=[_chunk("a")], graph_used=broaden))
    _patch_stream(monkeypatch, ["draft"])  # first-pass tokens only
    # First pass ungrounded; the first correction round grounds (2nd verify call).
    monkeypatch.setattr(answer.ollama_client, "generate", _ground_on_check({"grounds": 0}, 2))

    events = _collect("q", Settings(router_enabled=False, self_correct_enabled=True))

    # The grounded round is committed: exactly one replace + its answer swapped in.
    assert sum(1 for e in events if e["type"] == "replace") == 1
    assert "refined answer" in _tokens(events)
    final = events[-1]
    assert final["type"] == "final"
    assert final["corrected"] is True
    assert final["grounded"] is True


def test_stream_iterative_only_commits_grounded_round(monkeypatch):
    """Several rounds run, but only the grounded one is committed (one replace)."""
    _patch_gather(
        monkeypatch,
        lambda broaden: RetrievalBundle(
            chunks=[_chunk("a")], graph_notes=["x calls y"] if broaden else [], graph_used=broaden
        ),
    )
    _patch_stream(monkeypatch, ["draft"])
    # Ground only on the 3rd verify call (first pass + 2 correction rounds).
    monkeypatch.setattr(answer.ollama_client, "generate", _ground_on_check({"grounds": 0}, 3))

    events = _collect(
        "q",
        Settings(
            router_enabled=False, self_correct_enabled=True,
            iterative_enabled=True, iterative_max_rounds=3,
        ),
    )

    # Two rounds ran but only the grounded one commits -> exactly one replace.
    assert sum(1 for e in events if e["type"] == "replace") == 1
    final = events[-1]
    assert final["corrected"] is True
    assert final["grounded"] is True


def test_stream_ungrounded_keeps_first_pass(monkeypatch):
    """No round grounds -> the first-pass answer stays (matches blocking /query)."""
    _patch_gather(monkeypatch, lambda broaden: RetrievalBundle(chunks=[_chunk("a")], graph_used=broaden))
    _patch_stream(monkeypatch, ["first answer"])

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        if system and "verify" in system.lower():
            return '{"grounded": false, "unsupported": ["claim"]}'
        return "discarded retry"  # generated but never committed (never grounds)

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)

    events = _collect(
        "q",
        Settings(
            router_enabled=False, self_correct_enabled=True,
            iterative_enabled=True, iterative_max_rounds=3,
        ),
    )

    assert not any(e["type"] == "replace" for e in events)  # nothing committed
    assert _tokens(events) == "first answer"  # only the first pass is shown
    final = events[-1]
    assert final["corrected"] is False
    assert final["grounded"] is False
    assert final["unsupported"] == ["claim"]


def test_stream_and_blocking_agree_when_ungrounded(monkeypatch):
    """/query and /query/stream return the same answer/grounded/corrected when
    no correction round grounds — the whole point of the conservative unification."""
    _patch_gather(monkeypatch, lambda broaden: RetrievalBundle(chunks=[_chunk("a")], graph_used=broaden))
    _patch_stream(monkeypatch, ["the answer"])  # first-pass tokens for the stream

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        if system and "verify" in system.lower():
            return '{"grounded": false, "unsupported": ["c"]}'
        return "the answer"  # blocking first pass + all (discarded) retries

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)
    cfg = Settings(
        router_enabled=False, self_correct_enabled=True,
        iterative_enabled=True, iterative_max_rounds=3,
    )

    blocking = asyncio.run(answer.answer_question("q", settings=cfg))
    events = _collect("q", cfg)
    final = events[-1]

    assert _tokens(events) == blocking.answer == "the answer"
    assert final["grounded"] == blocking.grounded is False
    assert final["corrected"] == blocking.corrected is False


def test_stream_self_correction_failure_falls_back(monkeypatch):
    """If the correction re-retrieval fails, fall through to the first-pass final."""

    async def fake_gather(question, route, settings, *, broaden=False, k=None, extra_queries=None):
        if broaden:
            raise httpx.HTTPError("embed down")
        return RetrievalBundle(chunks=[_chunk("a")])

    monkeypatch.setattr(answer.context, "gather", fake_gather)
    _patch_stream(monkeypatch, ["draft"])
    _patch_grounding(monkeypatch, '{"grounded": false, "unsupported": ["x"]}')

    events = _collect("q", Settings(router_enabled=False, self_correct_enabled=True))

    assert not any(e["type"] == "replace" for e in events)  # correction never started
    final = events[-1]
    assert final["type"] == "final"
    assert final["corrected"] is False
    assert final["grounded"] is False
