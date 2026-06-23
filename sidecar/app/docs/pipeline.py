"""Documentation ingestion orchestrator (Index C).

Chunk → embed → store, tracked by a single in-process job so the frontend can
show progress. Run as a separate action from code/history indexing. Unlike those,
docs need no LLM step (prose is embedded directly), so this is the fastest of the
three pipelines.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client, sqlite_store
from app.docs.splitter import chunk_docs_repo
from app.index import docs_index
from app.index.docs_index import DocChunkRecord
from app.llm import ollama_client

# Number of chunks embedded + written per batch.
_BATCH_SIZE = 16


class DocsJob(BaseModel):
    """Live status of a documentation indexing run."""

    state: str = "idle"  # idle | running | done | error
    repo: str | None = None
    total: int = 0
    processed: int = 0
    errors: list[str] = []
    message: str | None = None


_job = DocsJob()


def current_job() -> DocsJob:
    return _job


def is_running() -> bool:
    return _job.state == "running"


def mark_running(repo: str) -> DocsJob:
    """Synchronously mark a job running before its task is scheduled."""
    global _job
    _job = DocsJob(state="running", repo=repo, message="Queued…")
    return _job


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def index_docs(repo_path: Path) -> DocsJob:
    """Index a repository's documentation into LanceDB, updating job status."""
    global _job
    settings = get_settings()
    repo = repo_path.name
    _job = DocsJob(state="running", repo=repo, message="Scanning docs…")

    try:
        # Ensure the embedded stores exist even when run outside the app lifespan.
        sqlite_store.init_schema(settings.data_path)

        chunks = chunk_docs_repo(repo_path)
        _job.total = len(chunks)
        _job.message = "Indexing…"

        db = lancedb_client.connect(settings.data_path)
        docs_index.delete_repo(db, repo)

        for batch in _batches(chunks, _BATCH_SIZE):
            try:
                texts = [c.text for c in batch]
                vectors = await ollama_client.embed_many(
                    settings.ollama_url,
                    settings.embedding_model,
                    texts,
                    concurrency=settings.embed_concurrency,
                )
                records = [
                    DocChunkRecord(vector=vector, **chunk.model_dump())
                    for chunk, vector in zip(batch, vectors)
                ]
                docs_index.upsert(db, records)
            except (httpx.HTTPError, ValueError) as error:
                _job.errors.append(f"batch failed: {error}")
            finally:
                _job.processed += len(batch)

        # Rebuild the full-text index so keyword/hybrid search covers new rows.
        docs_index.ensure_fts_index(db, force=True)

        _job.state = "done"
        _job.message = f"Indexed {_job.processed} doc chunks"
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
