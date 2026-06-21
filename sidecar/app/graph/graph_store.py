"""Persistence for the static dependency graph (SQLite graph_nodes/edges)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass

from app.graph.imports import ImportEdge

STATIC_LAYER = "static"
IMPORT_EDGE = "imports"


def _node_key(repo: str, file_path: str) -> str:
    return f"module:{repo}:{file_path}"


@dataclass(frozen=True)
class GraphData:
    """A loaded static graph: nodes (repo-relative paths) and directed edges."""

    nodes: list[str]
    edges: list[tuple[str, str]]  # (src_file, dst_file)


def replace_repo_graph(
    conn: sqlite3.Connection,
    repo: str,
    nodes: list[str],
    edges: list[ImportEdge],
) -> None:
    """Replace this repo's static graph with a freshly built one (idempotent)."""
    with conn:
        # Remove the repo's existing static edges, then its nodes.
        conn.execute(
            """
            DELETE FROM graph_edges
            WHERE layer = ?
              AND src_key IN (SELECT node_key FROM graph_nodes WHERE repo = ?)
            """,
            (STATIC_LAYER, repo),
        )
        conn.execute("DELETE FROM graph_nodes WHERE repo = ?", (repo,))

        conn.executemany(
            "INSERT INTO graph_nodes (node_key, node_type, name, file_path, repo) "
            "VALUES (?, 'module', ?, ?, ?)",
            [(_node_key(repo, n), n, n, repo) for n in nodes],
        )
        conn.executemany(
            "INSERT INTO graph_edges (src_key, dst_key, edge_type, layer) "
            "VALUES (?, ?, ?, ?)",
            [
                (_node_key(repo, e.src_file), _node_key(repo, e.dst_file), IMPORT_EDGE, STATIC_LAYER)
                for e in edges
            ],
        )


def load_static_graph(conn: sqlite3.Connection, repo: str | None = None) -> GraphData:
    """Load the static graph (optionally scoped to one repo) as file-path edges."""
    if repo is not None:
        node_rows = conn.execute(
            "SELECT file_path FROM graph_nodes WHERE repo = ?", (repo,)
        ).fetchall()
        edge_rows = conn.execute(
            """
            SELECT s.file_path AS src, d.file_path AS dst
            FROM graph_edges e
            JOIN graph_nodes s ON s.node_key = e.src_key
            JOIN graph_nodes d ON d.node_key = e.dst_key
            WHERE e.layer = ? AND s.repo = ?
            """,
            (STATIC_LAYER, repo),
        ).fetchall()
    else:
        node_rows = conn.execute(
            "SELECT file_path FROM graph_nodes WHERE node_type = 'module'"
        ).fetchall()
        edge_rows = conn.execute(
            """
            SELECT s.file_path AS src, d.file_path AS dst
            FROM graph_edges e
            JOIN graph_nodes s ON s.node_key = e.src_key
            JOIN graph_nodes d ON d.node_key = e.dst_key
            WHERE e.layer = ?
            """,
            (STATIC_LAYER,),
        ).fetchall()

    nodes = [row[0] for row in node_rows]
    edges = [(row[0], row[1]) for row in edge_rows]
    return GraphData(nodes=nodes, edges=edges)


def upsert_repo(conn: sqlite3.Connection, name: str, path: str) -> None:
    """Record (or update) the on-disk path of an indexed repository."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO repos (name, path, indexed_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET path = excluded.path, "
            "indexed_at = excluded.indexed_at",
            (name, path, now),
        )


def get_repo_path(conn: sqlite3.Connection, name: str) -> str | None:
    """Return the absolute path recorded for an indexed repo, or None."""
    row = conn.execute("SELECT path FROM repos WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def list_repos(conn: sqlite3.Connection) -> list[str]:
    """Return the names of all indexed repos."""
    return [row[0] for row in conn.execute("SELECT name FROM repos ORDER BY name")]
