"""Tests for the code index and ingestion pipeline.

The embedding call is monkeypatched (no Ollama needed) and enrichment is disabled,
so this exercises chunk -> embed -> LanceDB end to end against a temp data dir.
"""

from __future__ import annotations

import asyncio

from app.config import Settings, get_settings
from app.db import lancedb_client
from app.index import code_index
from app.index.code_index import _EMBEDDING_DIM
from app.ingest import pipeline


def _write_repo(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text(
        "def add(a, b):\n    return a + b\n\nclass Calc:\n    def mul(self, a, b):\n        return a * b\n",
        encoding="utf-8",
    )
    (root / "b.py").write_text("import os\n\ndef cwd():\n    return os.getcwd()\n", encoding="utf-8")


def test_index_repo_writes_chunks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    data_dir = tmp_path / "data"
    test_settings = Settings(data_dir=data_dir, enrich_enabled=False, embed_concurrency=2)

    # Point the pipeline and stats at the temp settings.
    monkeypatch.setattr(pipeline, "get_settings", lambda: test_settings)

    # Fake embeddings: deterministic vectors of the right dimension, no network.
    async def fake_embed_many(base_url, model, texts, **kwargs):
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(pipeline.ollama_client, "embed_many", fake_embed_many)

    job = asyncio.run(pipeline.index_repo(repo))

    assert job.state == "done"
    assert job.total > 0
    assert job.processed == job.total
    assert not job.errors

    db = lancedb_client.connect(data_dir)
    assert code_index.count(db) == job.total

    # A vector search returns rows with the expected metadata fields.
    results = code_index.search(db, [0.1] * _EMBEDDING_DIM, k=3)
    assert results
    assert {"symbol", "file_path", "kind"} <= set(results[0].keys())


def test_reindex_is_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    data_dir = tmp_path / "data"
    test_settings = Settings(data_dir=data_dir, enrich_enabled=False)
    monkeypatch.setattr(pipeline, "get_settings", lambda: test_settings)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        return [[0.2] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(pipeline.ollama_client, "embed_many", fake_embed_many)

    first = asyncio.run(pipeline.index_repo(repo))
    second = asyncio.run(pipeline.index_repo(repo))

    db = lancedb_client.connect(data_dir)
    # Re-indexing the same repo must not duplicate rows.
    assert code_index.count(db) == first.total == second.total


def test_get_settings_singleton_unaffected():
    # Sanity: the real settings singleton still resolves (default data dir).
    assert isinstance(get_settings(), Settings)
