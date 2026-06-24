"""Source viewer API: read a window of an indexed file for click-through citations.

Given a repo + relative file path + a cited line range, return the lines around
that range so the frontend can show the cited code in-app. Read-only and tightly
scoped: only files **inside an indexed repository's root** can be read, and the
resolved path is checked so it cannot escape that root (path-traversal guard).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite_store
from app.graph import graph_store

router = APIRouter(tags=["source"])


class SourceView(BaseModel):
    """A window of a file's lines around a cited range."""

    repo: str
    file_path: str
    start_line: int  # cited range (1-based, inclusive)
    end_line: int
    window_start: int  # 1-based line number of ``lines[0]``
    lines: list[str]


def _is_within(target: Path, root: Path) -> bool:
    """True if ``target`` is the same as or inside ``root`` (both resolved)."""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


@router.get("/source", response_model=SourceView)
def read_source(
    repo: str = Query(..., description="Indexed repository name"),
    path: str = Query(..., description="File path relative to the repo root"),
    start: int = Query(1, ge=1, description="First cited line (1-based)"),
    end: int = Query(1, ge=1, description="Last cited line (1-based)"),
) -> SourceView:
    """Return a context window of a cited file (read-only, repo-scoped)."""
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        root_str = graph_store.get_repo_path(conn, repo)
    finally:
        conn.close()
    if root_str is None:
        raise HTTPException(status_code=400, detail=f"Unknown repository: {repo}")

    root = Path(root_str).resolve()
    target = (root / path).resolve()
    if not _is_within(target, root):
        raise HTTPException(status_code=403, detail="Path escapes the repository root")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    total = max(1, len(all_lines))

    # Clamp the cited range to the file, then widen by the context window.
    start = min(start, total)
    end = max(start, min(end, total))
    ctx = settings.source_view_context
    window_start = max(1, start - ctx)
    window_end = min(len(all_lines), end + ctx)
    lines = all_lines[window_start - 1 : window_end]

    return SourceView(
        repo=repo,
        file_path=path,
        start_line=start,
        end_line=end,
        window_start=window_start,
        lines=lines,
    )
