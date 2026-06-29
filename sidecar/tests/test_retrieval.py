"""Tests for hybrid retrieval and the cross-encoder reranker.

No network and no model download: embeddings and the cross-encoder are
monkeypatched. The LanceDB FTS/hybrid path runs for real against a temp dir.
"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.db import lancedb_client
from app.index import code_index
from app.index.code_index import _EMBEDDING_DIM, CodeChunkRecord
from app.retrieval import hybrid, reranker


def _seed(data_dir):
    """Create a code_chunks table with three distinguishable rows + FTS index."""
    db = lancedb_client.connect(data_dir)
    rows = [
        ("retry", "retry failed API calls with exponential backoff"),
        ("dbpool", "create the database connection pool"),
        ("auth", "refresh the authentication token"),
    ]
    records = [
        CodeChunkRecord(
            vector=[0.1] * _EMBEDDING_DIM,
            chunk_id=cid,
            repo="r",
            file_path=f"{cid}.py",
            language="python",
            kind="function",
            symbol=cid,
            qualified_name=f"{cid}.py::{cid}",
            start_line=1,
            end_line=2,
            code=f"def {cid}(): ...",
            enriched_text=text,
        )
        for cid, text in rows
    ]
    code_index.upsert(db, records)
    code_index.ensure_fts_index(db, force=True)
    return db


def test_rerank_disabled_preserves_order():
    settings = Settings(rerank_enabled=False)
    docs = ["a", "b", "c"]
    assert reranker.rerank("q", docs, settings) == [0, 1, 2]


def test_rerank_orders_by_score(monkeypatch):
    settings = Settings(rerank_enabled=True)

    class FakeEncoder:
        def rerank(self, query, documents):
            # Pretend the 3rd doc is most relevant, then 1st, then 2nd.
            return [0.5, 0.1, 0.9]

    monkeypatch.setattr(reranker, "_get_encoder", lambda model, cache_dir: FakeEncoder())
    order = reranker.rerank("q", ["x", "y", "z"], settings, top_k=2)
    assert order == [2, 0]


def test_rerank_failure_falls_back_to_rrf_order(monkeypatch):
    settings = Settings(rerank_enabled=True)

    class Boom:
        def rerank(self, query, documents):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(reranker, "_get_encoder", lambda model, cache_dir: Boom())
    assert reranker.rerank("q", ["x", "y", "z"], settings) == [0, 1, 2]


def _rc(cid: str) -> hybrid.RetrievedChunk:
    return hybrid.RetrievedChunk(
        chunk_id=cid,
        repo="r",
        file_path=f"{cid}.py",
        language="python",
        kind="function",
        symbol=cid,
        qualified_name=f"{cid}.py::{cid}",
        start_line=1,
        end_line=2,
        code="",
        score=1.0,
    )


def test_retrieve_multi_rrf_fuses_and_dedupes(monkeypatch):
    lists = {
        "q1": [_rc("a"), _rc("b"), _rc("c")],
        "q2": [_rc("b"), _rc("d")],
    }

    async def fake_retrieve(question, *, k=None, settings=None):
        return lists[question]

    monkeypatch.setattr(hybrid, "retrieve", fake_retrieve)

    results = asyncio.run(hybrid.retrieve_multi(["q1", "q2"], k=3, settings=Settings()))
    ids = [c.chunk_id for c in results]
    assert ids[0] == "b"  # in both lists -> highest fused score
    assert ids == ["b", "a", "d"]  # top-3 by RRF; "c" drops off
    assert len(ids) == len(set(ids))  # deduped


def test_retrieve_multi_skips_failed_subquery(monkeypatch):
    async def fake_retrieve(question, *, k=None, settings=None):
        if question == "bad":
            raise ValueError("embed failed")
        return [_rc("a"), _rc("b")]

    monkeypatch.setattr(hybrid, "retrieve", fake_retrieve)
    # "bad" raises but must not abort the fusion — the surviving list is returned.
    results = asyncio.run(hybrid.retrieve_multi(["good", "bad"], k=3, settings=Settings()))
    assert [c.chunk_id for c in results] == ["a", "b"]


def test_retrieve_multi_single_query_delegates(monkeypatch):
    async def fake_retrieve(question, *, k=None, settings=None):
        assert question == "only"
        return [_rc("a")]

    monkeypatch.setattr(hybrid, "retrieve", fake_retrieve)
    # blanks/dupes are dropped, leaving a single effective query
    results = asyncio.run(hybrid.retrieve_multi(["only", "  ", "only"], settings=Settings()))
    assert [c.chunk_id for c in results] == ["a"]


def test_hybrid_retrieve_finds_keyword_match(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _seed(data_dir)
    settings = Settings(data_dir=data_dir, rerank_enabled=False)

    async def fake_embed(base_url, model, text, **kwargs):
        return [0.1] * _EMBEDDING_DIM

    monkeypatch.setattr(hybrid.ollama_client, "embed", fake_embed)

    results = asyncio.run(hybrid.retrieve("exponential backoff", settings=settings))
    assert results, "expected at least one result"
    # All vectors are identical, so FTS keyword match must surface the retry chunk.
    assert results[0].symbol == "retry"
    assert {"file_path", "symbol", "kind"} <= set(results[0].model_dump().keys())
