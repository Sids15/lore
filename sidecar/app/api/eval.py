"""Evaluation API: run the golden-set eval and report quality metrics."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite_store
from app.eval import harness
from app.eval.harness import EvalJob
from app.graph import graph_store

router = APIRouter(tags=["eval"])


class EvalRequest(BaseModel):
    """Which repo to evaluate (defaults to the only/first indexed repo)."""

    repo: str | None = None


def _resolve_repo_path(repo: str | None) -> Path | None:
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        name = repo
        if name is None:
            names = graph_store.list_repos(conn)
            name = names[0] if names else None
        path = graph_store.get_repo_path(conn, name) if name else None
    finally:
        conn.close()
    return Path(path) if path else None


@router.post("/eval/run", response_model=EvalJob, status_code=202)
async def start_eval(request: EvalRequest) -> EvalJob:
    """Start an evaluation run against the repo's `.lore/eval.yml`."""
    repo_path = _resolve_repo_path(request.repo)
    if repo_path is None or not repo_path.is_dir():
        raise HTTPException(status_code=400, detail="No indexed repository found")
    if harness.is_running():
        raise HTTPException(status_code=409, detail="An evaluation is already running")

    harness.mark_running(repo_path.name)
    asyncio.create_task(harness.run_eval(repo_path))
    return harness.current_job()


@router.get("/eval/status", response_model=EvalJob)
def eval_status() -> EvalJob:
    """Return the status (and report, when done) of the current/last eval run."""
    return harness.current_job()
