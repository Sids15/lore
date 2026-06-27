"""Tests for streamed Ollama generation (no network)."""

from __future__ import annotations

import asyncio
import json

from app.llm import ollama_client
from app.llm.ollama_client import _ThinkStripper


def test_think_stripper_passthrough():
    s = _ThinkStripper()
    out = s.feed("Hello ") + s.feed("world") + s.flush()
    assert out == "Hello world"


def test_think_stripper_removes_block_across_deltas():
    s = _ThinkStripper()
    out = (
        s.feed("Hello ")
        + s.feed("<think>reason")
        + s.feed("ing</think>")
        + s.feed("answer")
        + s.flush()
    )
    assert out == "Hello answer"


def test_think_stripper_handles_tag_split_mid_delta():
    s = _ThinkStripper()
    out = s.feed("a<thi") + s.feed("nk>x</thi") + s.feed("nk>b") + s.flush()
    assert out == "ab"


# --- generate_stream against a faked httpx streaming client ---------------------


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse(self._lines)

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def stream(self, method: str, url: str, json=None):  # noqa: A002 - mirror httpx
        return _FakeStreamCtx(self._lines)


def _collect(agen) -> list[str]:
    async def run() -> list[str]:
        return [chunk async for chunk in agen]

    return asyncio.run(run())


def test_generate_stream_yields_deltas(monkeypatch):
    lines = [
        json.dumps({"response": "Hello"}),
        json.dumps({"response": " world"}),
        json.dumps({"response": "", "done": True}),
    ]
    monkeypatch.setattr(
        ollama_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines)
    )

    chunks = _collect(ollama_client.generate_stream("http://x", "m", "p"))
    assert "".join(chunks) == "Hello world"


def test_generate_stream_strips_think_blocks(monkeypatch):
    lines = [
        json.dumps({"response": "<think>plan"}),
        json.dumps({"response": "ning</think>The "}),
        json.dumps({"response": "answer.", "done": True}),
    ]
    monkeypatch.setattr(
        ollama_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines)
    )

    chunks = _collect(ollama_client.generate_stream("http://x", "m", "p"))
    assert "".join(chunks) == "The answer."


def test_generate_stream_skips_malformed_lines(monkeypatch):
    lines = ["not json", json.dumps({"response": "ok", "done": True})]
    monkeypatch.setattr(
        ollama_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines)
    )

    chunks = _collect(ollama_client.generate_stream("http://x", "m", "p"))
    assert "".join(chunks) == "ok"
