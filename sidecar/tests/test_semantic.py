"""Tests for semantic graph building and persistence."""

from __future__ import annotations

from app.db import sqlite_store
from app.graph import graph_store, semantic
from app.graph.imports import ImportEdge
from app.ingest.ast_chunker import CodeChunk
from app.ingest.enrich import EntityRelations


def _entity(symbol: str, file_path: str, kind: str = "function") -> CodeChunk:
    return CodeChunk(
        chunk_id=f"{file_path}::{symbol}",
        repo="r",
        file_path=file_path,
        language="python",
        kind=kind,
        symbol=symbol,
        qualified_name=f"{file_path}::{symbol}",
        start_line=1,
        end_line=2,
        code=f"def {symbol}(): ...",
    )


def test_resolves_call_edge_same_file():
    caller = _entity("a", "m.py")
    callee = _entity("b", "m.py")
    relations = {caller.chunk_id: EntityRelations(calls=["b()"])}

    nodes, edges = semantic.build_semantic_graph([caller, callee], relations)

    assert {n.qualified_name for n in nodes} == {"m.py::a", "m.py::b"}
    assert len(edges) == 1
    assert (edges[0].src, edges[0].dst, edges[0].edge_type) == ("m.py::a", "m.py::b", "calls")


def test_ambiguous_name_across_files_is_skipped():
    caller = _entity("a", "m.py")
    t1 = _entity("dup", "x.py")
    t2 = _entity("dup", "y.py")
    relations = {caller.chunk_id: EntityRelations(calls=["dup"])}

    _, edges = semantic.build_semantic_graph([caller, t1, t2], relations)
    assert edges == []  # ambiguous across files -> no edge


def test_unique_global_match_resolves():
    caller = _entity("a", "m.py")
    callee = _entity("helper", "util.py")
    relations = {caller.chunk_id: EntityRelations(calls=["helper"])}

    _, edges = semantic.build_semantic_graph([caller, callee], relations)
    assert len(edges) == 1
    assert edges[0].dst == "util.py::helper"


def test_inherits_edge_typing():
    child = _entity("Child", "m.py", kind="class")
    base = _entity("Base", "m.py", kind="class")
    relations = {child.chunk_id: EntityRelations(extends=["Base"])}

    _, edges = semantic.build_semantic_graph([child, base], relations)
    assert edges[0].edge_type == "inherits"


def test_persist_semantic_does_not_disturb_static(tmp_path):
    data_dir = tmp_path / "data"
    sqlite_store.init_schema(data_dir)
    conn = sqlite_store.connect(data_dir)
    try:
        # Static graph first.
        graph_store.replace_static_graph(
            conn, "r", ["m.py", "util.py"], [ImportEdge("m.py", "util.py")]
        )
        # Then semantic graph.
        nodes, edges = semantic.build_semantic_graph(
            [_entity("a", "m.py"), _entity("helper", "util.py")],
            {"m.py::a": EntityRelations(calls=["helper"])},
        )
        graph_store.replace_semantic_graph(conn, "r", nodes, edges)

        static = graph_store.load_graph(conn, "r", "static")
        sem = graph_store.load_graph(conn, "r", "semantic")
    finally:
        conn.close()

    assert ("m.py", "util.py") in static.edges  # static intact
    assert ("m.py::a", "util.py::helper") in sem.edges  # semantic present
