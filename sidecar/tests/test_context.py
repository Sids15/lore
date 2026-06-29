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


def test_extra_queries_route_through_multi_retrieve(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    captured: dict[str, list[str]] = {}

    async def fake_multi(queries, *, k=None, settings=None):
        captured["queries"] = queries
        return [_chunk("m.py::a", "a")]

    async def fail_retrieve(*args, **kwargs):
        raise AssertionError("single-query retrieve should not run when extra_queries given")

    monkeypatch.setattr(context.hybrid, "retrieve_multi", fake_multi)
    monkeypatch.setattr(context.hybrid, "retrieve", fail_retrieve)

    bundle = asyncio.run(
        context.gather(
            "main q",
            RouteDecision(categories=["code"]),
            Settings(data_dir=data),
            broaden=True,
            extra_queries=["claim one", "  ", "claim two"],
        )
    )
    # The main question leads, blanks are dropped.
    assert captured["queries"] == ["main q", "claim one", "claim two"]
    assert len(bundle.chunks) == 1


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


def _doc_hit(heading: str = "Setup") -> context.DocHit:
    return context.DocHit(
        chunk_id="d1",
        repo="r",
        file_path="README.md",
        heading=heading,
        start_line=1,
        end_line=4,
        text="Install the dependencies first.",
        score=1.0,
    )


def test_docs_route_pulls_doc_hits(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    _patch_retrieve(monkeypatch, [])

    async def fake_search_docs(question, *, k=None, settings=None):
        return [_doc_hit()]

    monkeypatch.setattr(context.docs_retrieval, "search_docs", fake_search_docs)

    bundle = asyncio.run(
        context.gather("how do I install?", RouteDecision(categories=["docs"]), Settings(data_dir=data))
    )
    assert len(bundle.docs) == 1
    assert bundle.docs[0].file_path == "README.md"


def test_code_route_skips_docs(monkeypatch, tmp_path):
    data = tmp_path / "data"
    _seed(data)
    _patch_retrieve(monkeypatch, [_chunk("m.py::a", "a")])

    async def fail_search_docs(*args, **kwargs):
        raise AssertionError("docs search should not run for a code-only route")

    monkeypatch.setattr(context.docs_retrieval, "search_docs", fail_search_docs)

    bundle = asyncio.run(
        context.gather("where is a?", RouteDecision(categories=["code"]), Settings(data_dir=data))
    )
    assert bundle.docs == []


def test_format_context_includes_docs_section():
    bundle = context.RetrievalBundle(chunks=[], docs=[_doc_hit("Setup > Linux")])
    text = context.format_context(bundle)
    assert "From the documentation" in text
    assert "README.md:1-4" in text
    assert "Setup > Linux" in text
