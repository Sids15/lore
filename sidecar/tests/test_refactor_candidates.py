"""Tests for deterministic refactor-candidate detection (no network)."""

from __future__ import annotations

from app.config import Settings
from app.db import sqlite_store
from app.graph import graph_store
from app.graph.imports import ImportEdge
from app.refactor.candidates import detect_candidates


def _conn(tmp_path):
    data = tmp_path / "data"
    sqlite_store.init_schema(data)
    return sqlite_store.connect(data)


def test_detects_cycle_and_hub(tmp_path):
    conn = _conn(tmp_path)
    try:
        nodes = ["a.py", "b.py", "hub.py", "i1.py", "i2.py", "o1.py", "o2.py"]
        edges = [
            ImportEdge("a.py", "b.py"),
            ImportEdge("b.py", "a.py"),  # cycle a <-> b
            ImportEdge("i1.py", "hub.py"),
            ImportEdge("i2.py", "hub.py"),  # hub in-degree 2
            ImportEdge("hub.py", "o1.py"),
            ImportEdge("hub.py", "o2.py"),  # hub out-degree 2
        ]
        graph_store.replace_static_graph(conn, "r", nodes, edges)

        candidates = detect_candidates(conn, "r", Settings(refactor_hub_degree=2))
        by_kind = {c.kind for c in candidates}
        assert "cycle" in by_kind
        assert "hub" in by_kind

        hub = next(c for c in candidates if c.kind == "hub")
        assert "hub.py" in hub.files
        assert hub.severity == "medium"

        cycle = next(c for c in candidates if c.kind == "cycle")
        assert set(cycle.files) == {"a.py", "b.py"}
        assert cycle.severity == "high"
    finally:
        conn.close()


def test_no_candidates_for_clean_graph(tmp_path):
    conn = _conn(tmp_path)
    try:
        graph_store.replace_static_graph(
            conn, "r", ["a.py", "b.py"], [ImportEdge("a.py", "b.py")]
        )
        candidates = detect_candidates(conn, "r", Settings(refactor_hub_degree=2))
        assert candidates == []
    finally:
        conn.close()


def test_detects_architecture_violation(tmp_path):
    repo_dir = tmp_path / "repo"
    (repo_dir / ".lore").mkdir(parents=True)
    (repo_dir / ".lore" / "arch-rules.yml").write_text(
        "layers:\n"
        '  api: ["sidecar/app/api/**"]\n'
        '  frontend: ["src/**"]\n'
        "rules:\n"
        '  - name: "API must not depend on the frontend"\n'
        "    from: api\n"
        "    to: frontend\n"
        "    severity: error\n",
        encoding="utf-8",
    )

    conn = _conn(tmp_path)
    try:
        nodes = ["sidecar/app/api/x.py", "src/y.py"]
        graph_store.replace_static_graph(
            conn, "repo", nodes, [ImportEdge("sidecar/app/api/x.py", "src/y.py")]
        )
        graph_store.upsert_repo(conn, "repo", str(repo_dir.resolve()))

        candidates = detect_candidates(conn, "repo", Settings())
        violation = next(c for c in candidates if c.kind == "violation")
        assert violation.severity == "high"  # rule severity 'error'
        assert "src/y.py" in violation.files
    finally:
        conn.close()
