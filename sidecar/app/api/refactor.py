"""Refactoring API: list structural candidates and propose a fix for one."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite_store
from app.refactor.candidates import RefactorCandidate, detect_candidates
from app.refactor.suggest import suggest_refactor

router = APIRouter(tags=["refactor"])


class RefactorResponse(BaseModel):
    """The detected refactor candidates for a repo."""

    repo: str | None
    candidates: list[RefactorCandidate]


class SuggestResponse(BaseModel):
    """An LLM refactor proposal for a candidate."""

    proposal: str


@router.get("/refactor", response_model=RefactorResponse)
def refactor(repo: str | None = None) -> RefactorResponse:
    """List refactoring candidates for the repo (deterministic, no LLM)."""
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        candidates = detect_candidates(conn, repo, settings)
    finally:
        conn.close()
    return RefactorResponse(repo=repo, candidates=candidates)


@router.post("/refactor/suggest", response_model=SuggestResponse)
async def suggest(candidate: RefactorCandidate) -> SuggestResponse:
    """Generate a grounded refactor proposal for one candidate (LLM)."""
    proposal = await suggest_refactor(candidate)
    return SuggestResponse(proposal=proposal)
