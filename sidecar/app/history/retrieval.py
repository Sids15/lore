"""Query the git-history index.

Semantic + keyword search over commit summaries (LanceDB hybrid), returning typed
commit hits the query layer can fold into an answer.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import lancedb_client
from app.history import history_index
from app.llm import ollama_client


class CommitHit(BaseModel):
    """A commit returned from history search."""

    sha: str
    author: str
    committed_at: str
    message: str
    summary: str
    files: str
    score: float

    @classmethod
    def from_row(cls, row: dict) -> CommitHit:
        return cls(
            sha=row["sha"],
            author=row["author"],
            committed_at=row["committed_at"],
            message=row["message"],
            summary=row.get("summary") or "",
            files=row.get("files") or "",
            score=float(row.get("_relevance_score") or 0.0),
        )


async def search_history(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> list[CommitHit]:
    """Return the commits most relevant to a question (hybrid search on summaries)."""
    settings = settings or get_settings()
    top_k = k or settings.retrieval_top_k

    query_vector = await ollama_client.embed(
        settings.ollama_url, settings.embedding_model, question
    )
    db = lancedb_client.connect(settings.data_path)
    rows = history_index.hybrid_search(db, query_vector, question, top_k)
    return [CommitHit.from_row(row) for row in rows]
