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


def _patch(monkeypatch, settings, counter=None):
    monkeypatch.setattr(docs_pipeline, "get_settings", lambda: settings)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        if counter is not None:
            counter.append(len(texts))
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
    # Incremental: the second pass finds nothing changed (no new chunks), and the
    # stored chunk count is unchanged — no duplicates.
    assert docs_index.count(db) == first.total
    assert second.total == 0


def test_repo_with_no_docs_is_done_with_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    _patch(monkeypatch, Settings(data_dir=tmp_path / "data"))

    job = asyncio.run(docs_pipeline.index_docs(repo))
    assert job.state == "done"
    assert job.total == 0


def test_reindex_only_embeds_changed_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_docs(repo)
    data = tmp_path / "data"
    counter: list[int] = []
    _patch(monkeypatch, Settings(data_dir=data), counter=counter)

    asyncio.run(docs_pipeline.index_docs(repo))
    first_embeds = sum(counter)
    assert first_embeds > 0

    # Re-index with no changes: nothing is embedded.
    counter.clear()
    second = asyncio.run(docs_pipeline.index_docs(repo))
    assert sum(counter) == 0
    assert second.total == 0
    assert "unchanged" in (second.message or "")

    # Edit one file: only that file is re-embedded.
    counter.clear()
    (repo / "notes.txt").write_text("A changed note with more words now.\n", encoding="utf-8")
    third = asyncio.run(docs_pipeline.index_docs(repo))
    assert sum(counter) > 0
    assert third.message.startswith("1 changed")


def test_deleted_file_is_pruned(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_docs(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    asyncio.run(docs_pipeline.index_docs(repo))
    db = lancedb_client.connect(data)
    before = docs_index.count(db)

    (repo / "notes.txt").unlink()
    job = asyncio.run(docs_pipeline.index_docs(repo))

    assert docs_index.count(db) < before  # notes.txt chunks removed
    assert "1 removed" in (job.message or "")


def test_force_reindexes_everything(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_docs(repo)
    data = tmp_path / "data"
    counter: list[int] = []
    _patch(monkeypatch, Settings(data_dir=data), counter=counter)

    asyncio.run(docs_pipeline.index_docs(repo))
    counter.clear()

    job = asyncio.run(docs_pipeline.index_docs(repo, force=True))
    assert sum(counter) > 0  # everything re-embedded despite no changes
    assert job.state == "done"
