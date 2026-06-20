"""Indexing API: trigger and monitor code-index ingestion."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client
from app.index import code_index
from app.ingest import pipeline
from app.ingest.pipeline import IndexJob

router = APIRouter(prefix="/index", tags=["index"])


class IndexRequest(BaseModel):
    """Request body for starting a code-index run."""

    path: str


class IndexStats(BaseModel):
    """Aggregate counts for the indexes."""

    code_chunks: int


@router.post("/code", response_model=IndexJob, status_code=202)
async def start_code_index(request: IndexRequest) -> IndexJob:
    """Start indexing the repository at ``path`` (one job at a time)."""
    repo_path = Path(request.path).expanduser()
    if not repo_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")
    if pipeline.is_running():
        raise HTTPException(status_code=409, detail="An indexing job is already running")

    # Mark running synchronously so the response and any immediate poll/retry see
    # the active job, then launch in the background (progress via GET /index/status).
    pipeline.mark_running(repo_path.name)
    asyncio.create_task(pipeline.index_repo(repo_path))
    return pipeline.current_job()


@router.get("/status", response_model=IndexJob)
def index_status() -> IndexJob:
    """Return the status of the current/last indexing run."""
    return pipeline.current_job()


@router.get("/stats", response_model=IndexStats)
def index_stats() -> IndexStats:
    """Return aggregate index counts."""
    settings = get_settings()
    db = lancedb_client.connect(settings.data_path)
    return IndexStats(code_chunks=code_index.count(db))
