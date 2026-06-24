"""Tests for multi-turn conversation (condense + history-aware answering)."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.query import answer, condense
from app.query.condense import ConversationTurn, condense_question, format_history
from app.query.context import RetrievalBundle
from app.retrieval.hybrid import RetrievedChunk


def _turn(q: str, a: str) -> ConversationTurn:
    return ConversationTurn(question=q, answer=a)


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


# --- condense_question --------------------------------------------------------


def test_condense_returns_question_without_history(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("LLM should not be called without history")

    monkeypatch.setattr(condense.ollama_client, "generate", boom)
    out = asyncio.run(condense_question("hi", [], Settings()))
    assert out == "hi"


def test_condense_disabled_returns_question(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when disabled")

    monkeypatch.setattr(condense.ollama_client, "generate", boom)
    out = asyncio.run(
        condense_question("and that?", [_turn("q", "a")], Settings(conversation_enabled=False))
    )
    assert out == "and that?"


def test_condense_rewrites_with_history(monkeypatch):
    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        return "  What does the retry helper do?  "

    monkeypatch.setattr(condense.ollama_client, "generate", fake_generate)
    out = asyncio.run(condense_question("explain that", [_turn("where is retry?", "retry.py")], Settings()))
    assert out == "What does the retry helper do?"


def test_condense_fails_open_on_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(condense.ollama_client, "generate", boom)
    out = asyncio.run(condense_question("explain that", [_turn("q", "a")], Settings()))
    assert out == "explain that"


def test_format_history_caps_turns():
    turns = [_turn(f"q{i}", f"a{i}") for i in range(10)]
    text = format_history(turns, 2)
    assert "q9" in text and "q8" in text
    assert "q7" not in text  # only the last 2 turns kept


# --- answer_question with history --------------------------------------------


def test_history_drives_retrieval_on_standalone_question(monkeypatch):
    captured: dict = {}
    prompts: list[tuple[str | None, str]] = []

    async def fake_gather(question, route, settings, *, broaden=False, k=None):
        captured["q"] = question
        return RetrievalBundle(chunks=[_chunk("retry")])

    monkeypatch.setattr(answer.context, "gather", fake_gather)

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        prompts.append((system, prompt))
        s = (system or "").lower()
        if "standalone" in s:
            return "What does the retry helper do?"
        if "verify" in s:
            return '{"grounded": true}'
        return "The retry helper retries failed calls [retry.py:1]."

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)

    resp = asyncio.run(
        answer.answer_question(
            "explain that further",
            settings=Settings(router_enabled=False),
            history=[_turn("where is retry?", "It's in retry.py")],
        )
    )

    # Retrieval used the condensed standalone question, not the bare follow-up.
    assert captured["q"] == "What does the retry helper do?"
    # The generation prompt carried the conversation context.
    assert any("Conversation so far" in p for _, p in prompts)
    assert resp.grounded is True


def test_no_history_skips_condense(monkeypatch):
    captured: dict = {}

    async def fake_gather(question, route, settings, *, broaden=False, k=None):
        captured["q"] = question
        return RetrievalBundle(chunks=[_chunk("a")])

    monkeypatch.setattr(answer.context, "gather", fake_gather)

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        s = (system or "").lower()
        if "standalone" in s:
            raise AssertionError("condense should not run without history")
        if "verify" in s:
            return '{"grounded": true}'
        return "answer [a.py:1]"

    monkeypatch.setattr(answer.ollama_client, "generate", fake_generate)

    asyncio.run(answer.answer_question("where is a?", settings=Settings(router_enabled=False)))
    assert captured["q"] == "where is a?"  # used verbatim
