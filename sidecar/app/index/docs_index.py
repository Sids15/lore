"""LanceDB vector index for documentation chunks (Index C).

Mirrors `code_index.py` / `history_index.py`: stores each doc chunk's embedded
text plus metadata, with idempotent upserts (by `chunk_id`), per-repo deletion,
an FTS index on the text, and hybrid (vector + keyword) search.
"""

from __future__ import annotations

from lancedb.db import DBConnection
from lancedb.pydantic import LanceModel, Vector

from app.config import get_settings

_EMBEDDING_DIM = get_settings().embedding_dim
FTS_COLUMN = "text"


class DocChunkRecord(LanceModel):
    """A documentation chunk plus its embedding, as stored in LanceDB."""

    vector: Vector(_EMBEDDING_DIM)  # type: ignore[valid-type]
    chunk_id: str
    repo: str
    file_path: str
    heading: str
    start_line: int
    end_line: int
    text: str


def _table_name() -> str:
    return get_settings().doc_table


def _exists(db: DBConnection) -> bool:
    return _table_name() in db.list_tables().tables


def open_table(db: DBConnection):
    name = _table_name()
    if _exists(db):
        return db.open_table(name)
    return db.create_table(name, schema=DocChunkRecord)


def _quote(value: str) -> str:
    return value.replace("'", "''")


def upsert(db: DBConnection, records: list[DocChunkRecord]) -> int:
    """Insert records, replacing any existing rows with the same chunk_id."""
    if not records:
        return 0
    table = open_table(db)
    ids = ", ".join(f"'{_quote(r.chunk_id)}'" for r in records)
    table.delete(f"chunk_id IN ({ids})")
    table.add(records)
    return len(records)


def delete_repo(db: DBConnection, repo: str) -> None:
    """Remove all chunks belonging to a repository (for a clean re-index)."""
    if _exists(db):
        db.open_table(_table_name()).delete(f"repo = '{_quote(repo)}'")


def count(db: DBConnection) -> int:
    """Total number of indexed documentation chunks."""
    if not _exists(db):
        return 0
    return db.open_table(_table_name()).count_rows()


def ensure_fts_index(db: DBConnection, *, force: bool = False) -> None:
    """Ensure a full-text index exists on the doc text column."""
    if not _exists(db):
        return
    table = open_table(db)
    has_fts = any(FTS_COLUMN in (idx.columns or []) for idx in table.list_indices())
    if force or not has_fts:
        table.create_fts_index(FTS_COLUMN, replace=True)


def hybrid_search(
    db: DBConnection, query_vector: list[float], query_text: str, k: int
) -> list[dict]:
    """Hybrid (vector + FTS) search merged with LanceDB's built-in RRF reranker."""
    if not _exists(db):
        return []
    ensure_fts_index(db)
    table = open_table(db)
    return (
        table.search(query_type="hybrid")
        .vector(query_vector)
        .text(query_text)
        .limit(k)
        .to_list()
    )
