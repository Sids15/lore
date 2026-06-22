"""LanceDB vector index for commit summaries (Index B).

Mirrors `code_index.py`: stores each commit's embedded summary plus metadata, with
idempotent upserts, per-repo deletion, an FTS index on the summary, and hybrid
(vector + keyword) search.
"""

from __future__ import annotations

from lancedb.db import DBConnection
from lancedb.pydantic import LanceModel, Vector

from app.config import get_settings

_EMBEDDING_DIM = get_settings().embedding_dim
FTS_COLUMN = "summary"


class CommitRecord(LanceModel):
    """A commit summary plus its embedding, as stored in LanceDB."""

    vector: Vector(_EMBEDDING_DIM)  # type: ignore[valid-type]
    sha: str
    repo: str
    author: str
    committed_at: str
    message: str
    summary: str
    files: str  # comma-joined changed file paths


def _table_name() -> str:
    return get_settings().history_table


def _exists(db: DBConnection) -> bool:
    return _table_name() in db.list_tables().tables


def open_table(db: DBConnection):
    name = _table_name()
    if _exists(db):
        return db.open_table(name)
    return db.create_table(name, schema=CommitRecord)


def _quote(value: str) -> str:
    return value.replace("'", "''")


def upsert(db: DBConnection, records: list[CommitRecord]) -> int:
    if not records:
        return 0
    table = open_table(db)
    ids = ", ".join(f"'{_quote(r.sha)}'" for r in records)
    table.delete(f"sha IN ({ids})")
    table.add(records)
    return len(records)


def delete_repo(db: DBConnection, repo: str) -> None:
    if _exists(db):
        db.open_table(_table_name()).delete(f"repo = '{_quote(repo)}'")


def count(db: DBConnection) -> int:
    if not _exists(db):
        return 0
    return db.open_table(_table_name()).count_rows()


def ensure_fts_index(db: DBConnection, *, force: bool = False) -> None:
    if not _exists(db):
        return
    table = open_table(db)
    has_fts = any(FTS_COLUMN in (idx.columns or []) for idx in table.list_indices())
    if force or not has_fts:
        table.create_fts_index(FTS_COLUMN, replace=True)


def hybrid_search(db: DBConnection, query_vector: list[float], query_text: str, k: int) -> list[dict]:
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
