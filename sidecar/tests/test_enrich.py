"""Tests for contextual enrichment (no network: the LLM call is monkeypatched)."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.ingest import enrich
from app.ingest.ast_chunker import CodeChunk


def _chunk() -> CodeChunk:
    return CodeChunk(
        chunk_id="x",
        repo="r",
        file_path="a.py",
        language="python",
        kind="function",
        symbol="f",
        qualified_name="a.py::f",
        start_line=1,
        end_line=2,
        code="def f():\n    return 1",
    )


def test_disabled_returns_raw_code():
    settings = Settings(enrich_enabled=False)
    chunk = _chunk()
    assert asyncio.run(enrich.enrich_chunk(chunk, settings)) == chunk.code


def test_disabled_batch_returns_raw_code():
    settings = Settings(enrich_enabled=False)
    chunks = [_chunk()]
    assert asyncio.run(enrich.enrich_chunks(chunks, settings)) == [chunks[0].code]


def test_enabled_prepends_header(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return "Returns the integer one."

    monkeypatch.setattr(enrich.ollama_client, "generate", fake_generate)
    settings = Settings(enrich_enabled=True)
    chunk = _chunk()

    out = asyncio.run(enrich.enrich_chunk(chunk, settings))
    assert out.startswith("Returns the integer one.")
    assert chunk.code in out


def test_failure_falls_back_to_code(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("ollama down")

    monkeypatch.setattr(enrich.ollama_client, "generate", boom)
    settings = Settings(enrich_enabled=True)
    chunk = _chunk()

    assert asyncio.run(enrich.enrich_chunk(chunk, settings)) == chunk.code
