"""Ingestion orchestrator for the Code Index.

Ties the stages together — chunk → enrich → embed → store — and tracks progress
in a single in-process job so the frontend can show a live status bar.

Processing is done in batches so progress advances incrementally and memory stays
bounded on large repositories. Only one job runs at a time.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client
from app.index import code_index
from app.index.code_index import CodeChunkRecord
from app.ingest.ast_chunker import chunk_repo
from app.ingest.enrich import enrich_chunks
from app.llm import ollama_client

# Number of chunks processed (enriched + embedded + written) per batch.
_BATCH_SIZE = 16


class IndexJob(BaseModel):
    """Live status of the current/last indexing run."""

    state: str = "idle"  # idle | running | done | error
    repo: str | None = None
    total: int = 0
    processed: int = 0
    errors: list[str] = []
    message: str | None = None


_job = IndexJob()


def current_job() -> IndexJob:
    """Return the current job status."""
    return _job


def is_running() -> bool:
    return _job.state == "running"


def mark_running(repo: str) -> IndexJob:
    """Synchronously mark a job as running before its task is scheduled.

    Closes the race where two requests could both start a job in the gap between
    scheduling the task and the task actually beginning.
    """
    global _job
    _job = IndexJob(state="running", repo=repo, message="Queued…")
    return _job


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def index_repo(repo_path: Path) -> IndexJob:
    """Index a repository's code into LanceDB, updating the job status as it goes."""
    global _job
    settings = get_settings()

    _job = IndexJob(state="running", repo=repo_path.name, message="Scanning files…")

    try:
        chunks = chunk_repo(repo_path)
        _job.total = len(chunks)
        _job.message = "Indexing…"

        db = lancedb_client.connect(settings.data_path)
        code_index.delete_repo(db, repo_path.name)

        for batch in _batches(chunks, _BATCH_SIZE):
            try:
                texts = await enrich_chunks(batch, settings)
                vectors = await ollama_client.embed_many(
                    settings.ollama_url,
                    settings.embedding_model,
                    texts,
                    concurrency=settings.embed_concurrency,
                )
                records = [
                    CodeChunkRecord(vector=vector, enriched_text=text, **chunk.model_dump())
                    for chunk, text, vector in zip(batch, texts, vectors)
                ]
                code_index.upsert(db, records)
            except (httpx.HTTPError, ValueError) as error:
                _job.errors.append(f"batch failed: {error}")
            finally:
                _job.processed += len(batch)

        # Rebuild the full-text index so keyword/hybrid search covers the new rows.
        code_index.ensure_fts_index(db, force=True)

        _job.state = "done"
        _job.message = f"Indexed {_job.processed} chunks"
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
