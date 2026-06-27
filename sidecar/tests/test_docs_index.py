"""Tests for the documentation LanceDB table module (no network)."""

from __future__ import annotations

from app.db import lancedb_client
from app.index import docs_index
from app.index.docs_index import _EMBEDDING_DIM, DocChunkRecord


def _record(chunk_id: str, repo: str = "r") -> DocChunkRecord:
    return DocChunkRecord(
        vector=[0.1] * _EMBEDDING_DIM,
        chunk_id=chunk_id,
        repo=repo,
        file_path="README.md",
        heading="Guide",
        start_line=1,
        end_line=4,
        text="some documentation prose about setup",
    )


def test_upsert_count_and_idempotent_reupsert(tmp_path):
    db = lancedb_client.connect(tmp_path / "data")
    assert docs_index.count(db) == 0

    docs_index.upsert(db, [_record("a"), _record("b")])
    assert docs_index.count(db) == 2

    # Re-upserting the same ids replaces rather than duplicates.
    docs_index.upsert(db, [_record("a")])
    assert docs_index.count(db) == 2


def test_delete_repo_removes_only_that_repo(tmp_path):
    db = lancedb_client.connect(tmp_path / "data")
    docs_index.upsert(db, [_record("a", repo="one"), _record("b", repo="two")])
    docs_index.delete_repo(db, "one")
    assert docs_index.count(db) == 1


def test_hybrid_search_returns_rows(tmp_path):
    db = lancedb_client.connect(tmp_path / "data")
    docs_index.upsert(db, [_record("a"), _record("b")])
    docs_index.ensure_fts_index(db, force=True)

    rows = docs_index.hybrid_search(db, [0.1] * _EMBEDDING_DIM, "setup", k=5)
    assert rows
    assert {"chunk_id", "file_path", "heading", "text"} <= set(rows[0].keys())
