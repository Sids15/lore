"""Tests for docs ingestion (no network: embeddings mocked)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.db import lancedb_client
from app.docs import pipeline as docs_pipeline
from app.index import docs_index
from app.index.docs_index import _EMBEDDING_DIM


def _write_docs(root):
    root.mkdir()
    (root / "README.md").write_text(
        "# Project\n\nThis project does things.\n\n## Setup\n\nInstall and run.\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("A plain text note.\n", encoding="utf-8")
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")  # ignored: not a doc


def _patch(monkeypatch, settings):
    monkeypatch.setattr(docs_pipeline, "get_settings", lambda: settings)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(docs_pipeline.ollama_client, "embed_many", fake_embed_many)


def test_index_docs_stores_chunks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_docs(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    job = asyncio.run(docs_pipeline.index_docs(repo))
    assert job.state == "done"
    assert job.total > 0
    assert job.processed == job.total
    assert not job.errors

    db = lancedb_client.connect(data)
    assert docs_index.count(db) == job.total


def test_reindex_is_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_docs(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    first = asyncio.run(docs_pipeline.index_docs(repo))
    second = asyncio.run(docs_pipeline.index_docs(repo))

    db = lancedb_client.connect(data)
    assert docs_index.count(db) == first.total == second.total


def test_repo_with_no_docs_is_done_with_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    _patch(monkeypatch, Settings(data_dir=tmp_path / "data"))

    job = asyncio.run(docs_pipeline.index_docs(repo))
    assert job.state == "done"
    assert job.total == 0
