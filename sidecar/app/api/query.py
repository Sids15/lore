"""Query API: ask a grounded question about the indexed code."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.query.answer import AnswerResponse, answer_question

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    """Request body for a question."""

    question: str
    k: int | None = None  # override the number of chunks retrieved


@router.post("/query", response_model=AnswerResponse)
async def query(request: QueryRequest) -> AnswerResponse:
    """Answer a natural-language question about the indexed repository."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")
    try:
        return await answer_question(question, k=request.k)
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=503,
            detail=f"LLM/embedding service unavailable: {error}",
        ) from error
