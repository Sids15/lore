"""Tests for query expansion (no network: the LLM is mocked)."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.query import expand


def _run(question: str, settings: Settings) -> list[str]:
    return asyncio.run(expand.expand_query(question, settings))


def _patch_generate(monkeypatch, raw: str) -> None:
    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        return raw

    monkeypatch.setattr(expand.ollama_client, "generate", fake_generate)


def test_disabled_returns_empty_without_calling_llm(monkeypatch):
    async def fail_generate(*args, **kwargs):
        raise AssertionError("generate must not run when expansion is disabled")

    monkeypatch.setattr(expand.ollama_client, "generate", fail_generate)
    assert _run("how does auth work?", Settings(query_expansion_enabled=False)) == []


def test_parses_caps_and_drops_echo(monkeypatch):
    _patch_generate(
        monkeypatch,
        '{"queries": ["how does auth work?", "session authentication flow", '
        '"login token handling", "user credential check"]}',
    )
    out = _run(
        "how does auth work?",
        Settings(query_expansion_enabled=True, query_expansion_n=2),
    )
    # The echo of the original question is dropped; result is capped to n=2.
    assert out == ["session authentication flow", "login token handling"]


def test_llm_error_fails_open(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.HTTPError("ollama down")

    monkeypatch.setattr(expand.ollama_client, "generate", boom)
    assert _run("q", Settings(query_expansion_enabled=True)) == []


def test_unparseable_output_returns_empty(monkeypatch):
    _patch_generate(monkeypatch, "sorry, I can't help with that")
    assert _run("q", Settings(query_expansion_enabled=True)) == []
