"""Tests for routed context assembly / GraphRAG (no network)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.db import sqlite_store
from app.graph import graph_store
from app.graph.graph_store import SemanticEdge, SemanticNode
from app.graph.imports import ImportEdge
from app.query import context
from app.query.router import RouteDecision
from app.retrieval.hybrid import RetrievedChunk


def _chunk(qualified_name: str, symbol: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=qualified_name,
        repo="r",
        file_path=qualified_name.split("::")[0],
        language="python",
        kind="function",
        symbol=symbol,
        qualified_name=qualified_name,
        start_line=1,
        end_line=2,
        code=f"def {symbol}(): ...",
        score=1.0,
    )


def _seed(data_dir):
    sqlite_store.init_schema(data_dir)
    conn = sqlite_store.connect(data_dir)
    try:
        graph_store.replace_semantic_graph(
            conn,
            "r",
            [SemanticNode("m.py::a", "function", "m.py"), SemanticNode("m.py::b", "function", "m.py")],
            [SemanticEdge("m.py::a", "m.py::b", "calls")],
        )
        graph_store.replace_static_graph(
            conn, "r", ["x.py", "y.py"], [ImportEdge("x.py", "y.py"), ImportEdge("y.py", "x.py")]
        )
    finally:
        conn.close()


def _patch_retrieve(monkeypatch, chunks):
    async def fake_retrieve(question, *, k=None, settings=None):
        return chunks

    monkeypatch.setattr(context.hybrid, "retrieve", fake_retrieve)


def test_relational_adds_call_notes(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    _patch_retrieve(monkeypatch, [_chunk("m.py::a", "a")])

    bundle = asyncio.run(
        context.gather("what does a call?", RouteDecision(categories=["relational"]), Settings(data_dir=data))
    )
    assert bundle.graph_used is True
    assert any("a calls b" in note for note in bundle.graph_notes)


def test_architectural_reports_cycle(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    _patch_retrieve(monkeypatch, [_chunk("x.py::x", "x")])

    bundle = asyncio.run(
        context.gather("any cycles?", RouteDecision(categories=["architectural"]), Settings(data_dir=data))
    )
    assert any("Circular dependency" in note for note in bundle.graph_notes)


def test_code_route_skips_graph(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    _patch_retrieve(monkeypatch, [_chunk("m.py::a", "a")])

    bundle = asyncio.run(
        context.gather("where is a?", RouteDecision(categories=["code"]), Settings(data_dir=data))
    )
    assert bundle.graph_used is False
    assert bundle.graph_notes == []


def test_trivial_returns_empty():
    bundle = asyncio.run(
        context.gather("hi", RouteDecision(categories=["trivial"]), Settings())
    )
    assert bundle.chunks == []
    assert bundle.graph_used is False


def test_format_context_includes_graph_section():
    bundle = context.RetrievalBundle(
        chunks=[_chunk("m.py::a", "a")], graph_notes=["a calls b"], graph_used=True
    )
    text = context.format_context(bundle)
    assert "Related (from the code graph)" in text
    assert "a calls b" in text
