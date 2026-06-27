"""Hybrid retrieval orchestrator.

Embeds the question, runs LanceDB hybrid search (vector + FTS, merged with RRF) to
gather candidates, then reranks them with the cross-encoder and returns the top-k.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import lancedb_client
from app.index import code_index
from app.llm import ollama_client
from app.retrieval import reranker


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
    rerank_texts = [row.get("enriched_text") or row.get("code", "") for row in rows]
    order = reranker.rerank(question, rerank_texts, settings, top_k=top_k)
    return [candidates[i] for i in order]
