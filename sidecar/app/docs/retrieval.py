"""Query the documentation index (Index C).

Semantic + keyword search over doc chunks (LanceDB hybrid), returning typed doc
hits the query layer can fold into an answer.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import lancedb_client
from app.index import docs_index
from app.llm import ollama_client


class DocHit(BaseModel):
    """A documentation chunk returned from docs search."""

    chunk_id: str
    repo: str
    file_path: str
    heading: str
    start_line: int
    end_line: int
    text: str
    score: float

    @classmethod
    def from_row(cls, row: dict) -> "DocHit":
        return cls(
            chunk_id=row["chunk_id"],
            repo=row.get("repo") or "",
            file_path=row["file_path"],
            heading=row.get("heading") or "",
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            text=row.get("text") or "",
            score=float(row.get("_relevance_score") or 0.0),
        )


async def search_docs(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> list[DocHit]:
    """Return the doc chunks most relevant to a question (hybrid search)."""
    settings = settings or get_settings()
    top_k = k or settings.retrieval_top_k

    query_vector = await ollama_client.embed(
        settings.ollama_url, settings.embedding_model, question
    )
    db = lancedb_client.connect(settings.data_path)
    rows = docs_index.hybrid_search(db, query_vector, question, top_k)
    return [DocHit.from_row(row) for row in rows]
