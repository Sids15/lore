"""Tests for the code index and ingestion pipeline.

The embedding call is monkeypatched (no Ollama needed) and enrichment is disabled,
so this exercises chunk -> embed -> LanceDB end to end against a temp data dir.
"""

from __future__ import annotations

import asyncio

from app.config import Settings, get_settings
from app.db import lancedb_client, sqlite_store
from app.graph import graph_store
from app.index import code_index
from app.index.code_index import _EMBEDDING_DIM
from app.ingest import enrich, pipeline


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
    # Re-indexing the same repo must not duplicate rows; the second (incremental)
    # pass finds nothing changed.
    assert code_index.count(db) == first.total
    assert second.total == 0


def _patch_embeds(monkeypatch, settings, counter):
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        counter.append(len(texts))
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(pipeline.ollama_client, "embed_many", fake_embed_many)


def test_reindex_only_embeds_changed_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    data_dir = tmp_path / "data"
    counter: list[int] = []
    _patch_embeds(monkeypatch, Settings(data_dir=data_dir, enrich_enabled=False), counter)

    asyncio.run(pipeline.index_repo(repo))
    assert sum(counter) > 0

    # No changes: nothing re-embedded.
    counter.clear()
    second = asyncio.run(pipeline.index_repo(repo))
    assert sum(counter) == 0
    assert second.total == 0
    assert "unchanged" in (second.message or "")

    # Edit one file: only it is re-embedded.
    counter.clear()
    (repo / "b.py").write_text("import os\n\ndef cwd():\n    return os.getcwd() + '/'\n", encoding="utf-8")
    third = asyncio.run(pipeline.index_repo(repo))
    assert sum(counter) > 0
    assert third.message.startswith("1 changed")


def test_deleted_file_is_pruned(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    data_dir = tmp_path / "data"
    counter: list[int] = []
    _patch_embeds(monkeypatch, Settings(data_dir=data_dir, enrich_enabled=False), counter)

    asyncio.run(pipeline.index_repo(repo))
    db = lancedb_client.connect(data_dir)
    before = code_index.count(db)

    (repo / "b.py").unlink()
    job = asyncio.run(pipeline.index_repo(repo))
    assert code_index.count(db) < before
    assert "1 removed" in (job.message or "")


def test_force_reindexes_everything(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    data_dir = tmp_path / "data"
    counter: list[int] = []
    _patch_embeds(monkeypatch, Settings(data_dir=data_dir, enrich_enabled=False), counter)

    asyncio.run(pipeline.index_repo(repo))
    counter.clear()
    job = asyncio.run(pipeline.index_repo(repo, force=True))
    assert sum(counter) > 0  # everything re-embedded despite no changes
    assert job.state == "done"


def test_semantic_graph_preserved_on_noop_reindex(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def main():\n    return helper()\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, enrich_enabled=True, semantic_enabled=True)

    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        # Every entity "calls" helper -> resolves to a.py::helper for main.
        return '{"summary": "does things", "calls": ["helper"], "extends": [], "implements": [], "intent": "glue"}'

    monkeypatch.setattr(enrich.ollama_client, "generate", fake_generate)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(pipeline.ollama_client, "embed_many", fake_embed_many)

    asyncio.run(pipeline.index_repo(repo))
    conn = sqlite_store.connect(data_dir)
    try:
        before = graph_store.load_graph(conn, "repo", "semantic")
    finally:
        conn.close()
    assert len(before.edges) > 0  # main -> helper

    # Re-index with no changes: the semantic graph still has the same edges, even
    # though no file was re-enriched (relations came from the store).
    asyncio.run(pipeline.index_repo(repo))
    conn = sqlite_store.connect(data_dir)
    try:
        after = graph_store.load_graph(conn, "repo", "semantic")
    finally:
        conn.close()
    assert set(after.edges) == set(before.edges)


def test_get_by_qualified_names_filters(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    data_dir = tmp_path / "data"
    _patch_embeds(monkeypatch, Settings(data_dir=data_dir, enrich_enabled=False), [])

    asyncio.run(pipeline.index_repo(repo))
    db = lancedb_client.connect(data_dir)

    rows = code_index.get_by_qualified_names(
        db, "repo", ["pkg/a.py::Calc", "b.py::<module>", "missing::x"]
    )
    names = {r["qualified_name"] for r in rows}
    assert names == {"pkg/a.py::Calc", "b.py::<module>"}

    # Wrong repo -> no rows; empty names -> no rows.
    assert code_index.get_by_qualified_names(db, "other", ["pkg/a.py::Calc"]) == []
    assert code_index.get_by_qualified_names(db, "repo", []) == []


def test_get_settings_singleton_unaffected():
    # Sanity: the real settings singleton still resolves (default data dir).
    assert isinstance(get_settings(), Settings)
