"""SQLite store: the dependency/semantic graph and git-history tables.

The schema follows the PRD's data model (§7.3): commits and their changed files,
a blame map, per-author file coverage, and a single graph table pair that holds
both the *static* dependency graph (Layer A) and the *semantic* graph (Layer B),
distinguished by the ``layer`` column on edges.

All initialization is idempotent (``CREATE TABLE IF NOT EXISTS``) so it is safe
to run on every startup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_FILENAME = "lore.sqlite"

# Tables that must exist for the store to be considered ready.
EXPECTED_TABLES = {
    "commits",
    "commit_files",
    "blame",
    "authorship",
    "graph_nodes",
    "graph_edges",
    "repos",
}

# Schema definition. Each statement is idempotent.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    # --- Git-history index (Index B) ---
    """
    CREATE TABLE IF NOT EXISTS commits (
        sha          TEXT PRIMARY KEY,
        author       TEXT NOT NULL,
        author_email TEXT,
        committed_at TEXT NOT NULL,           -- ISO-8601 timestamp
        message      TEXT NOT NULL,           -- raw commit message
        summary      TEXT,                    -- LLM summary (this is what gets embedded)
        raw_diff     TEXT,                    -- stored for display, NOT embedded
        repo         TEXT                     -- owning repository
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commit_files (
        sha         TEXT NOT NULL,
        file_path   TEXT NOT NULL,
        change_type TEXT,                      -- added | modified | deleted | renamed
        PRIMARY KEY (sha, file_path),
        FOREIGN KEY (sha) REFERENCES commits (sha) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blame (
        repo             TEXT NOT NULL DEFAULT '',
        file_path        TEXT NOT NULL,
        function_name    TEXT NOT NULL,
        last_sha         TEXT,
        last_author      TEXT,
        last_modified_at TEXT,
        PRIMARY KEY (repo, file_path, function_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS authorship (
        repo         TEXT NOT NULL DEFAULT '',
        author       TEXT NOT NULL,
        file_path    TEXT NOT NULL,
        commit_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (repo, author, file_path)
    )
    """,
    # --- Graph index (Index A: Layer A static + Layer B semantic) ---
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        node_key  TEXT PRIMARY KEY,            -- stable id, e.g. "module:repo:src/auth.ts"
        node_type TEXT NOT NULL,               -- module | class | function | ...
        name      TEXT NOT NULL,
        file_path TEXT,
        repo      TEXT,                         -- owning repository (for per-repo rebuilds)
        metadata  TEXT                         -- JSON blob for extra attributes
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        src_key   TEXT NOT NULL,
        dst_key   TEXT NOT NULL,
        edge_type TEXT NOT NULL,               -- imports | calls | inherits | ...
        layer     TEXT NOT NULL,               -- 'static' (exact) | 'semantic' (approximate)
        metadata  TEXT,
        FOREIGN KEY (src_key) REFERENCES graph_nodes (node_key) ON DELETE CASCADE,
        FOREIGN KEY (dst_key) REFERENCES graph_nodes (node_key) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON graph_edges (src_key)",
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_dst ON graph_edges (dst_key)",
    "CREATE INDEX IF NOT EXISTS idx_commit_files_path ON commit_files (file_path)",
    "CREATE INDEX IF NOT EXISTS idx_commits_repo_date ON commits (repo, committed_at)",
    # --- Indexed repositories (path lookup for on-demand rule evaluation) ---
    """
    CREATE TABLE IF NOT EXISTS repos (
        name        TEXT PRIMARY KEY,
        path        TEXT NOT NULL,             -- absolute path on disk
        indexed_at  TEXT NOT NULL              -- ISO-8601 timestamp
    )
    """,
)


def db_path(data_dir: Path) -> Path:
    """Absolute path to the SQLite database file."""
    return data_dir / DB_FILENAME


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open a connection, ensuring the data directory exists.

    Rows are returned as :class:`sqlite3.Row` (dict-like) and foreign keys are
    enforced.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(data_dir))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply idempotent migrations to upgrade older databases in place."""

    def add_column_if_missing(table: str, column: str, decl: str) -> None:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    add_column_if_missing("graph_nodes", "repo", "TEXT")
    # Phase 6: per-repo scoping for the history tables.
    add_column_if_missing("commits", "repo", "TEXT")
    add_column_if_missing("blame", "repo", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing("authorship", "repo", "TEXT NOT NULL DEFAULT ''")


def init_schema(data_dir: Path) -> None:
    """Create all tables and indexes if they do not already exist."""
    conn = connect(data_dir)
    try:
        with conn:  # transaction: commit on success, rollback on error
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            _migrate(conn)
    finally:
        conn.close()


def is_ready(data_dir: Path) -> bool:
    """Return True if the database exists and all expected tables are present."""
    path = db_path(data_dir)
    if not path.exists():
        return False
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        conn.close()
    existing = {row[0] for row in rows}
    return EXPECTED_TABLES.issubset(existing)
