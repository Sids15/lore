"""Tests for static import extraction and graph persistence."""

from __future__ import annotations

from app.db import sqlite_store
from app.graph import graph_store
from app.graph.imports import extract_graph


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_python_import_resolution(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "app/__init__.py", "")
    _write(repo, "app/config.py", "VALUE = 1\n")
    _write(repo, "app/db/__init__.py", "")
    _write(repo, "app/db/store.py", "X = 1\n")
    _write(
        repo,
        "app/main.py",
        "from app.config import VALUE\nfrom app.db import store\nimport os\n",
    )

    nodes, edges = extract_graph(repo)
    pairs = {(e.src_file, e.dst_file) for e in edges}

    assert "app/main.py" in nodes
    assert ("app/main.py", "app/config.py") in pairs  # from-module resolves
    assert ("app/main.py", "app/db/store.py") in pairs  # imported name = submodule
    # `import os` is external -> no edge
    assert all(dst != "os" for _, dst in pairs)


def test_typescript_relative_imports(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "src/lib/api.ts", "export const x = 1;\n")
    _write(repo, "src/components/Panel.tsx", "export const P = 1;\n")
    _write(
        repo,
        "src/App.tsx",
        'import { x } from "./lib/api";\n'
        'import { P } from "./components/Panel";\n'
        'import React from "react";\n',
    )

    _, edges = extract_graph(repo)
    pairs = {(e.src_file, e.dst_file) for e in edges}

    assert ("src/App.tsx", "src/lib/api.ts") in pairs
    assert ("src/App.tsx", "src/components/Panel.tsx") in pairs
    assert all("react" not in dst for _, dst in pairs)  # bare specifier skipped


def test_rust_sibling_module(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "src/sidecar.rs", "pub fn run() {}\n")
    _write(repo, "src/lib.rs", "mod sidecar;\nuse sidecar::run;\n")

    _, edges = extract_graph(repo)
    pairs = {(e.src_file, e.dst_file) for e in edges}
    assert ("src/lib.rs", "src/sidecar.rs") in pairs


def test_graph_persists_and_reloads(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "app/config.py", "V = 1\n")
    _write(repo, "app/main.py", "from app.config import V\n")
    data_dir = tmp_path / "data"
    sqlite_store.init_schema(data_dir)

    nodes, edges = extract_graph(repo)
    conn = sqlite_store.connect(data_dir)
    try:
        graph_store.replace_static_graph(conn, "repo", nodes, edges)
        # Re-running must not duplicate (idempotent).
        graph_store.replace_static_graph(conn, "repo", nodes, edges)
        loaded = graph_store.load_static_graph(conn, "repo")
    finally:
        conn.close()

    assert "app/main.py" in loaded.nodes
    assert ("app/main.py", "app/config.py") in loaded.edges
    assert len(loaded.edges) == 1  # no duplication
