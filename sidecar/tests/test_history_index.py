"""Tests for history ingestion (no network: summarise + embed mocked)."""

from __future__ import annotations

import asyncio

import git
from git import Actor

from app.config import Settings
from app.db import lancedb_client, sqlite_store
from app.history import history_index, summarize
from app.history import pipeline as history_pipeline
from app.history.history_index import _EMBEDDING_DIM


def _build_repo(repo_dir):
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)
    alice = Actor("Alice", "alice@example.com")
    f = repo_dir / "m.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    repo.index.add(["m.py"])
    repo.index.commit(
        "add foo", author=alice, committer=alice,
        author_date="2026-01-01T00:00:00", commit_date="2026-01-01T00:00:00",
    )
    return repo


def _patch(monkeypatch, settings):
    monkeypatch.setattr(history_pipeline, "get_settings", lambda: settings)

    async def fake_generate(*args, **kwargs):
        return "Adds the foo function."

    monkeypatch.setattr(summarize.ollama_client, "generate", fake_generate)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(history_pipeline.ollama_client, "embed_many", fake_embed_many)


def test_index_history_stores_summaries(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    job = asyncio.run(history_pipeline.index_history(repo))
    assert job.state == "done"
    assert job.total == 1 and job.processed == 1

    db = lancedb_client.connect(data)
    assert history_index.count(db) == 1

    conn = sqlite_store.connect(data)
    try:
        summary = conn.execute("SELECT summary FROM commits WHERE repo = 'repo'").fetchone()[0]
    finally:
        conn.close()
    assert summary == "Adds the foo function."


def test_reindex_is_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    asyncio.run(history_pipeline.index_history(repo))
    asyncio.run(history_pipeline.index_history(repo))

    db = lancedb_client.connect(data)
    assert history_index.count(db) == 1  # no duplicate commit rows


def test_non_git_repo_reports_error(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    _patch(monkeypatch, Settings(data_dir=tmp_path / "data"))

    job = asyncio.run(history_pipeline.index_history(plain))
    assert job.state == "error"
    assert "git" in (job.message or "").lower()
