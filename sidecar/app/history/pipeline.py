"""Git-history ingestion orchestrator.

Walk → blame → summarise (LLM) → embed → store, tracked by a single in-process
job so the frontend can show progress. Run as a separate action from code
indexing (it is LLM-heavy: one summary per commit).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client, sqlite_store
from app.history import blame, git_walker, history_index, history_store, summarize
from app.history.history_index import CommitRecord
from app.ingest.ast_chunker import chunk_repo
from app.llm import ollama_client

_BATCH_SIZE = 16


class HistoryJob(BaseModel):
    """Live status of a git-history indexing run."""

    state: str = "idle"  # idle | running | done | error
    repo: str | None = None
    total: int = 0
    processed: int = 0
    errors: list[str] = []
    message: str | None = None


_job = HistoryJob()


def current_job() -> HistoryJob:
    return _job


def is_running() -> bool:
    return _job.state == "running"


def mark_running(repo: str) -> HistoryJob:
    global _job
    _job = HistoryJob(state="running", repo=repo, message="Queued…")
    return _job


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def index_history(repo_path: Path, *, force: bool = False) -> HistoryJob:
    """Index a repository's git history (summaries + blame + authorship).

    Incremental by default: commits are immutable, so only commits not already
    summarised get a (LLM) summary + embedding; existing summaries are preserved.
    Blame/authorship/commit rows are rebuilt every run (cheap, no LLM). ``force``
    re-summarises everything.
    """
    global _job
    settings = get_settings()
    repo = repo_path.name
    _job = HistoryJob(state="running", repo=repo, message="Reading commits…")

    try:
        sqlite_store.init_schema(settings.data_path)
        commits = git_walker.walk(repo_path, settings.history_max_commits)
        if commits is None:
            _job.state = "error"
            _job.message = "Not a git repository"
            return _job

        blame_entries = blame.blame_functions(repo_path, chunk_repo(repo_path))

        conn = sqlite_store.connect(settings.data_path)
        db = lancedb_client.connect(settings.data_path)
        try:
            # Which commits already have a summary? (Read before the rebuild nulls them.)
            preserved = {} if force else history_store.existing_summaries(conn, repo)
            if force:
                history_index.delete_repo(db, repo)

            # Structured data: rebuilt every run (idempotent, no LLM).
            history_store.replace_repo_history(conn, repo, commits, blame_entries)
            # Re-apply preserved summaries (their LanceDB rows are untouched).
            for sha, summary in preserved.items():
                history_store.set_summary(conn, sha, summary)

            to_summarise = [c for c in commits if c.sha not in preserved]
            _job.total = len(to_summarise)
            _job.message = "Summarising commits…"
            for batch in _batches(to_summarise, _BATCH_SIZE):
                try:
                    summaries = await summarize.summarise_many(batch, settings)
                    vectors = await ollama_client.embed_many(
                        settings.ollama_url,
                        settings.embedding_model,
                        summaries,
                        concurrency=settings.embed_concurrency,
                    )
                    records = [
                        CommitRecord(
                            vector=vector,
                            sha=c.sha,
                            repo=repo,
                            author=c.author,
                            committed_at=c.committed_at,
                            message=c.message,
                            summary=summary,
                            files=",".join(p for p, _ in c.files),
                        )
                        for c, summary, vector in zip(batch, summaries, vectors, strict=False)
                    ]
                    history_index.upsert(db, records)
                    for c, summary in zip(batch, summaries, strict=False):
                        history_store.set_summary(conn, c.sha, summary)
                except (httpx.HTTPError, ValueError) as error:
                    _job.errors.append(f"batch failed: {error}")
                finally:
                    _job.processed += len(batch)

            if to_summarise:
                history_index.ensure_fts_index(db, force=True)
        finally:
            conn.close()

        _job.state = "done"
        _job.message = f"{len(to_summarise)} new, {len(preserved)} unchanged"
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
