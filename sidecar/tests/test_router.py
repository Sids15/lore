"""Tests for the agentic query router (no network: generate mocked)."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.query import router


def test_disabled_router_defaults_to_code():
    decision = asyncio.run(router.classify("anything", Settings(router_enabled=False)))
    assert decision.categories == ["code"]


def test_parses_categories(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return '{"categories": ["architectural"], "reasoning": "asks about cycles"}'

    monkeypatch.setattr(router.ollama_client, "generate", fake_generate)
    decision = asyncio.run(router.classify("any cycles?", Settings()))
    assert decision.categories == ["architectural"]
    assert decision.needs_graph() is True
    assert decision.trivial is False


def test_invalid_categories_fall_back(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return '{"categories": ["banana"]}'

    monkeypatch.setattr(router.ollama_client, "generate", fake_generate)
    decision = asyncio.run(router.classify("q", Settings()))
    assert decision.categories == ["code"]


def test_docs_category_is_recognized(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return '{"categories": ["docs"], "reasoning": "answered by the README"}'

    monkeypatch.setattr(router.ollama_client, "generate", fake_generate)
    decision = asyncio.run(router.classify("how do I build the installer?", Settings()))
    assert decision.categories == ["docs"]
    assert decision.trivial is False


def test_trivial_is_normalized_alone(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return '{"categories": ["trivial", "code"]}'

    monkeypatch.setattr(router.ollama_client, "generate", fake_generate)
    decision = asyncio.run(router.classify("hi", Settings()))
    assert "trivial" not in decision.categories  # dropped when combined with real categories
    assert decision.categories == ["code"]


def test_llm_failure_falls_back(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(router.ollama_client, "generate", boom)
    decision = asyncio.run(router.classify("q", Settings()))
    assert decision.categories == ["code"]
