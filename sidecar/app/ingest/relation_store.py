"""Persistence for per-chunk semantic relations (for incremental code indexing).

The semantic graph (Graph Layer B) is built from the relations the enrichment LLM
extracts per chunk. To rebuild that graph during an incremental re-index — without
re-enriching unchanged files — we persist each chunk's relations here and reload
them, merging the stored (unchanged) relations with the freshly-enriched ones.
"""

from __future__ import annotations

import sqlite3

from app.ingest.enrich import EntityRelations


def save_relations(
    conn: sqlite3.Connection,
    repo: str,
    by_chunk: dict[str, EntityRelations],
    file_by_chunk: dict[str, str],
) -> None:
    """Upsert relations for the given chunks (keyed by chunk_id)."""
    if not by_chunk:
        return
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO chunk_relations (repo, chunk_id, file_path, relations) "
            "VALUES (?, ?, ?, ?)",
            [
                (repo, chunk_id, file_by_chunk.get(chunk_id, ""), relations.model_dump_json())
                for chunk_id, relations in by_chunk.items()
            ],
        )


def load_relations(conn: sqlite3.Connection, repo: str) -> dict[str, EntityRelations]:
    """Load all stored relations for a repo as ``{chunk_id: EntityRelations}``."""
    rows = conn.execute(
        "SELECT chunk_id, relations FROM chunk_relations WHERE repo = ?", (repo,)
    ).fetchall()
    return {row[0]: EntityRelations.model_validate_json(row[1]) for row in rows}


def delete_files(conn: sqlite3.Connection, repo: str, paths: list[str]) -> None:
    """Remove stored relations for the given files (changed or deleted)."""
    if not paths:
        return
    with conn:
        conn.executemany(
            "DELETE FROM chunk_relations WHERE repo = ? AND file_path = ?",
            [(repo, path) for path in paths],
        )


def clear_repo(conn: sqlite3.Connection, repo: str) -> None:
    """Drop all stored relations for a repo (used by a forced full re-index)."""
    with conn:
        conn.execute("DELETE FROM chunk_relations WHERE repo = ?", (repo,))
