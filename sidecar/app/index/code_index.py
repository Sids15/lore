"""LanceDB vector index for code chunks (Index A).

Stores each enriched, embedded chunk as a row with its vector and metadata, and
provides idempotent upserts (by `chunk_id`), per-repo deletion (for re-indexing),
counting, and vector search.
"""

from __future__ import annotations

from lancedb.db import DBConnection
from lancedb.pydantic import LanceModel, Vector

from app.config import get_settings

TABLE_NAME = "code_chunks"

# The embedding dimension is fixed when the table is created. It is read from
# settings at import time (nomic-embed-text -> 768).
_EMBEDDING_DIM = get_settings().embedding_dim


class CodeChunkRecord(LanceModel):
    """A code chunk plus its embedding, as stored in LanceDB."""

    vector: Vector(_EMBEDDING_DIM)  # type: ignore[valid-type]
    chunk_id: str
    repo: str
    file_path: str
    language: str
    kind: str
    symbol: str
    qualified_name: str
    start_line: int
    end_line: int
    code: str
    enriched_text: str


def _table_exists(db: DBConnection) -> bool:
    return TABLE_NAME in db.list_tables().tables


def open_table(db: DBConnection):
    """Open the code-chunks table, creating it (with schema) if absent."""
    if _table_exists(db):
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=CodeChunkRecord)


def _quote(value: str) -> str:
    """Escape a string for use in a LanceDB SQL filter."""
    return value.replace("'", "''")


def upsert(db: DBConnection, records: list[CodeChunkRecord]) -> int:
    """Insert records, replacing any existing rows with the same chunk_id."""
    if not records:
        return 0
    table = open_table(db)
    ids = ", ".join(f"'{_quote(record.chunk_id)}'" for record in records)
    table.delete(f"chunk_id IN ({ids})")
    table.add(records)
    return len(records)


def delete_repo(db: DBConnection, repo: str) -> None:
    """Remove all chunks belonging to a repository (for a clean re-index)."""
    if _table_exists(db):
        db.open_table(TABLE_NAME).delete(f"repo = '{_quote(repo)}'")


def count(db: DBConnection) -> int:
    """Total number of indexed code chunks."""
    if not _table_exists(db):
        return 0
    return db.open_table(TABLE_NAME).count_rows()


def search(db: DBConnection, vector: list[float], k: int = 5) -> list[dict]:
    """Return the k nearest chunks to a query vector."""
    if not _table_exists(db):
        return []
    return db.open_table(TABLE_NAME).search(vector).limit(k).to_list()


def _has_fts_index(table, column: str) -> bool:
    return any(column in (idx.columns or []) for idx in table.list_indices())


def ensure_fts_index(db: DBConnection, *, force: bool = False) -> None:
    """Ensure a full-text index exists on the configured text column.

    Building the FTS index is what enables keyword (and therefore hybrid) search.
    It is created over the existing rows, so no re-embedding is needed. Pass
    ``force=True`` after ingestion to rebuild it so newly added rows are covered.
    """
    if not _table_exists(db):
        return
    column = get_settings().fts_column
    table = db.open_table(TABLE_NAME)
    if force or not _has_fts_index(table, column):
        table.create_fts_index(column, replace=True)


def hybrid_search(
    db: DBConnection,
    query_vector: list[float],
    query_text: str,
    k: int,
) -> list[dict]:
    """Hybrid (vector + FTS) search merged with LanceDB's built-in RRF reranker.

    Returns up to ``k`` rows, each including a ``_relevance_score`` (RRF score).
    """
    if not _table_exists(db):
        return []
    ensure_fts_index(db)  # create on demand so already-indexed repos work
    table = db.open_table(TABLE_NAME)
    return (
        table.search(query_type="hybrid")
        .vector(query_vector)
        .text(query_text)
        .limit(k)
        .to_list()
    )
