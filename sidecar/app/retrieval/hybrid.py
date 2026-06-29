"""Hybrid retrieval orchestrator.

Embeds the question, runs LanceDB hybrid search (vector + FTS, merged with RRF) to
gather candidates, then reranks them with the cross-encoder and returns the top-k.
"""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import lancedb_client
from app.index import code_index
from app.llm import ollama_client
from app.retrieval import mmr, reranker


class RetrievedChunk(BaseModel):
    """A code chunk returned from retrieval (metadata only — no vector)."""

    chunk_id: str
    repo: str
    file_path: str
    language: str
    kind: str
    symbol: str
    qualified_name: str
    start_line: int
    end_line: int
    code: str
    score: float  # RRF relevance score from hybrid search

    @classmethod
    def from_row(cls, row: dict) -> RetrievedChunk:
        return cls(
            chunk_id=row["chunk_id"],
            repo=row["repo"],
            file_path=row["file_path"],
            language=row["language"],
            kind=row["kind"],
            symbol=row["symbol"],
            qualified_name=row["qualified_name"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            code=row["code"],
            score=float(row.get("_relevance_score") or 0.0),
        )


async def retrieve(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """Return the most relevant chunks for a question.

    Pipeline: embed question -> hybrid search (vector + FTS, RRF) for
    ``rerank_candidates`` -> cross-encoder rerank -> top ``k``.
    """
    settings = settings or get_settings()
    top_k = k or settings.retrieval_top_k

    query_vector = await ollama_client.embed(
        settings.ollama_url, settings.embedding_model, question
    )

    db = lancedb_client.connect(settings.data_path)
    rows = code_index.hybrid_search(
        db, query_vector, question, k=settings.rerank_candidates
    )
    if not rows:
        return []

    candidates = [RetrievedChunk.from_row(row) for row in rows]
    # Rerank against the enriched text (situating header + code) when available.
    # Ask for the full order so MMR can re-select the top_k from all candidates.
    rerank_texts = [row.get("enriched_text") or row.get("code", "") for row in rows]
    order = reranker.rerank(question, rerank_texts, settings, top_k=None)

    if settings.mmr_enabled:
        # Diversify the final selection using the candidate vectors (already in
        # the rows — no re-embedding). Falls open to the relevance order.
        vectors = [row.get("vector") for row in rows]
        order = mmr.select(order, vectors, k=top_k, lambda_=settings.mmr_lambda)
    else:
        order = order[:top_k]
    return [candidates[i] for i in order]


# Reciprocal Rank Fusion constant for merging ranked lists. 60 is the value from
# the original RRF paper and a common default.
RRF_K = 60


async def retrieve_multi(
    queries: list[str],
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """Retrieve for several queries and fuse the results with Reciprocal Rank Fusion.

    Used by the self-correction pass: the main question plus the grounding pass's
    unsupported claims are retrieved separately and merged, so evidence for the
    weak claims is pulled in rather than just "more of the same". Each query reuses
    the full :func:`retrieve` pipeline (hybrid search + rerank).
    """
    settings = settings or get_settings()
    top_k = k or settings.retrieval_top_k

    # De-duplicate and drop blank queries (preserve order).
    unique: list[str] = []
    for query in queries:
        query = (query or "").strip()
        if query and query not in unique:
            unique.append(query)
    if not unique:
        return []
    if len(unique) == 1:
        return await retrieve(unique[0], k=top_k, settings=settings)

    async def _safe_retrieve(query: str) -> list[RetrievedChunk]:
        # A transient failure (e.g. an embed error) drops just this query from the
        # fusion rather than aborting the whole retry; genuine bugs still propagate.
        try:
            return await retrieve(query, k=top_k, settings=settings)
        except (httpx.HTTPError, ValueError):
            return []

    ranked_lists = await asyncio.gather(*(_safe_retrieve(query) for query in unique))

    # RRF: a chunk's score is the sum of 1/(RRF_K + rank) across the lists it
    # appears in; keep the first chunk object seen for each id.
    scores: dict[str, float] = {}
    best: dict[str, RetrievedChunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            best.setdefault(chunk.chunk_id, chunk)

    fused = sorted(best.values(), key=lambda c: scores[c.chunk_id], reverse=True)
    return fused[:top_k]
