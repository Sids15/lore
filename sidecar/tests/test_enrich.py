"""Tests for enrichment + semantic extraction (no network: generate mocked)."""

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


def test_disabled_returns_raw_code_no_relations():
    settings = Settings(enrich_enabled=False)
    result = asyncio.run(enrich.enrich_chunk(_chunk(), settings))
    assert result.embedding_text == _chunk().code
    assert result.relations is None


def test_semantic_extraction_parses_json(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return (
            '{"summary": "Returns one.", "calls": ["g"], "extends": [], '
            '"implements": [], "intent": "demo"}'
        )

    monkeypatch.setattr(enrich.ollama_client, "generate", fake_generate)
    result = asyncio.run(enrich.enrich_chunk(_chunk(), Settings(semantic_enabled=True)))

    assert result.embedding_text.startswith("Returns one.")
    assert _chunk().code in result.embedding_text
    assert result.relations is not None
    assert result.relations.calls == ["g"]
    assert result.relations.intent == "demo"


def test_summary_only_when_semantic_disabled(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return "A plain header."

    monkeypatch.setattr(enrich.ollama_client, "generate", fake_generate)
    result = asyncio.run(
        enrich.enrich_chunk(_chunk(), Settings(semantic_enabled=False))
    )
    assert result.embedding_text.startswith("A plain header.")
    assert result.relations is None


def test_unparseable_json_falls_back_to_header(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return "not json, just prose"

    monkeypatch.setattr(enrich.ollama_client, "generate", fake_generate)
    result = asyncio.run(enrich.enrich_chunk(_chunk(), Settings(semantic_enabled=True)))
    assert result.embedding_text.startswith("not json, just prose")
    assert result.relations is None


def test_failure_falls_back_to_code(monkeypatch):
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("ollama down")

    monkeypatch.setattr(enrich.ollama_client, "generate", boom)
    result = asyncio.run(enrich.enrich_chunk(_chunk(), Settings()))
    assert result.embedding_text == _chunk().code
    assert result.relations is None


def test_batch_returns_one_result_per_chunk():
    settings = Settings(enrich_enabled=False)
    chunks = [_chunk(), _chunk()]
    results = asyncio.run(enrich.enrich_chunks(chunks, settings))
    assert len(results) == 2
    assert all(r.embedding_text == chunks[0].code for r in results)
