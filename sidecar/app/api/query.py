"""Query API: ask a grounded question about the indexed code."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.query.answer import AnswerResponse, answer_question, answer_question_stream

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


@router.post("/query/stream")
async def query_stream(request: QueryRequest) -> StreamingResponse:
    """Answer a question as a stream of newline-delimited JSON events.

    Each line is one event (see ``answer_question_stream``): ``meta`` (tags +
    sources), ``token`` deltas, ``status``/``replace`` hints, then a terminal
    ``final`` — or ``error`` if the LLM/embedding service fails mid-stream.
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    async def ndjson() -> AsyncIterator[str]:
        try:
            async for event in answer_question_stream(question, k=request.k):
                yield json.dumps(event) + "\n"
        except httpx.HTTPError as error:
            payload = {
                "type": "error",
                "detail": f"LLM/embedding service unavailable: {error}",
            }
            yield json.dumps(payload) + "\n"

    return StreamingResponse(ndjson(), media_type="application/x-ndjson")
