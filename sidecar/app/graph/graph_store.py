"""Persistence for the dependency graph (SQLite graph_nodes/edges).

Two layers coexist in the same tables, distinguished by node-key prefix and the
edge ``layer`` column:

* **static** — module nodes (`module:<repo>:<file>`) + `imports` edges (exact).
* **semantic** — entity nodes (`entity:<repo>:<qualified_name>`) + `calls` /
  `inherits` / `implements` edges (LLM-extracted, approximate).

Each layer is rebuilt independently so re-indexing one never clobbers the other.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.graph.imports import ImportEdge

STATIC_LAYER = "static"
SEMANTIC_LAYER = "semantic"
IMPORT_EDGE = "imports"


def _module_key(repo: str, file_path: str) -> str:
    return f"module:{repo}:{file_path}"


def _entity_key(repo: str, qualified_name: str) -> str:
    return f"entity:{repo}:{qualified_name}"


@dataclass(frozen=True)
class GraphData:
    """A loaded graph: node ids and directed (src, dst) edges."""

    nodes: list[str]
    edges: list[tuple[str, str]]


@dataclass(frozen=True)
class SemanticNode:
    """An entity (function/class/method) in the semantic graph."""

    qualified_name: str
    kind: str
    file_path: str
    intent: str = ""


@dataclass(frozen=True)
class SemanticEdge:
    """A semantic relationship between two entities (by qualified name)."""

    src: str
    dst: str
    edge_type: str  # calls | inherits | implements


def replace_static_graph(
    conn: sqlite3.Connection,
    repo: str,
    file_nodes: list[str],
    edges: list[ImportEdge],
) -> None:
    """Rebuild this repo's static (module/import) graph. Idempotent."""
    with conn:
        # Deleting the module nodes cascades their static edges (FK ON DELETE CASCADE).
        conn.execute(
            "DELETE FROM graph_nodes WHERE repo = ? AND node_key LIKE 'module:%'",
            (repo,),
        )
        conn.executemany(
            "INSERT INTO graph_nodes (node_key, node_type, name, file_path, repo) "
            "VALUES (?, 'module', ?, ?, ?)",
            [(_module_key(repo, n), n, n, repo) for n in file_nodes],
        )
        conn.executemany(
            "INSERT INTO graph_edges (src_key, dst_key, edge_type, layer) VALUES (?, ?, ?, ?)",
            [
                (_module_key(repo, e.src_file), _module_key(repo, e.dst_file), IMPORT_EDGE, STATIC_LAYER)
                for e in edges
            ],
        )


def replace_semantic_graph(
    conn: sqlite3.Connection,
    repo: str,
    nodes: list[SemanticNode],
    edges: list[SemanticEdge],
) -> None:
    """Rebuild this repo's semantic (entity/relationship) graph. Idempotent."""
    with conn:
        conn.execute(
            "DELETE FROM graph_nodes WHERE repo = ? AND node_key LIKE 'entity:%'",
            (repo,),
        )
        conn.executemany(
            "INSERT INTO graph_nodes (node_key, node_type, name, file_path, repo, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    _entity_key(repo, n.qualified_name),
                    n.kind,
                    n.qualified_name,
                    n.file_path,
                    repo,
                    json.dumps({"intent": n.intent}) if n.intent else None,
                )
                for n in nodes
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges (src_key, dst_key, edge_type, layer) VALUES (?, ?, ?, ?)",
            [
                (_entity_key(repo, e.src), _entity_key(repo, e.dst), e.edge_type, SEMANTIC_LAYER)
                for e in edges
            ],
        )


def load_graph(
    conn: sqlite3.Connection, repo: str | None = None, layer: str = STATIC_LAYER
) -> GraphData:
    """Load one layer of the graph as (node id, edges) using each node's ``name``.

    Node ids are file paths for the static layer and qualified names for the
    semantic layer (the `name` column holds both).
    """
    prefix = "module:%" if layer == STATIC_LAYER else "entity:%"

    node_sql = "SELECT name FROM graph_nodes WHERE node_key LIKE ?"
    node_params: list = [prefix]
    if repo is not None:
        node_sql += " AND repo = ?"
        node_params.append(repo)

    edge_sql = """
        SELECT s.name AS src, d.name AS dst
        FROM graph_edges e
        JOIN graph_nodes s ON s.node_key = e.src_key
        JOIN graph_nodes d ON d.node_key = e.dst_key
        WHERE e.layer = ?
    """
    edge_params: list = [layer]
    if repo is not None:
        edge_sql += " AND s.repo = ?"
        edge_params.append(repo)

    nodes = [row[0] for row in conn.execute(node_sql, node_params)]
    edges = [(row[0], row[1]) for row in conn.execute(edge_sql, edge_params)]
    return GraphData(nodes=nodes, edges=edges)


def load_static_graph(conn: sqlite3.Connection, repo: str | None = None) -> GraphData:
    """Backwards-compatible loader for the static graph."""
    return load_graph(conn, repo, STATIC_LAYER)


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
