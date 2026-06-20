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
