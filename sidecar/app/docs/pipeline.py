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
from app.docs.splitter import iter_doc_files, split_text
from app.graph import graph_store
from app.index import docs_index
from app.index.docs_index import DocChunkRecord
from app.ingest import file_state
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


async def index_docs(repo_path: Path, *, force: bool = False) -> DocsJob:
    """Index a repository's documentation into LanceDB, updating job status.

    Incremental by default: only files whose content hash changed (or are new)
    are re-chunked and re-embedded; deleted files are pruned. ``force=True`` does
    a full wipe-and-rebuild.
    """
    global _job
    settings = get_settings()
    repo = repo_path.name
    _job = DocsJob(state="running", repo=repo, message="Scanning docs…")

    try:
        # Ensure the embedded stores exist even when run outside the app lifespan.
        sqlite_store.init_schema(settings.data_path)

        files = iter_doc_files(repo_path)
        path_by_rel = {p.relative_to(repo_path).as_posix(): p for p in files}
        current = {rel: file_state.hash_file(p) for rel, p in path_by_rel.items()}

        db = lancedb_client.connect(settings.data_path)
        conn = sqlite_store.connect(settings.data_path)
        try:
            if force:
                docs_index.delete_repo(db, repo)
                file_state.clear_repo(conn, repo)

            diff = file_state.diff_files(conn, repo, current)
            # After a force-clear every file looks new; otherwise use the diff.
            to_index = diff.to_index
            to_delete = [] if force else diff.to_delete

            # Chunk only the files that need (re-)indexing.
            chunks = []
            for rel in to_index:
                text = path_by_rel[rel].read_text(encoding="utf-8", errors="replace")
                chunks.extend(split_text(text, repo=repo, file_path=rel, settings=settings))

            _job.total = len(chunks)
            _job.message = "Indexing…"

            # Clear stale rows for changed + deleted files before re-adding.
            docs_index.delete_files(db, repo, to_delete)

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

            # Rebuild the full-text index when rows changed.
            if chunks or to_delete:
                docs_index.ensure_fts_index(db, force=True)

            # Record the new hashes and drop deleted files from the index.
            file_state.record_files(conn, repo, current)
            file_state.prune(conn, repo, diff.deleted)
            # Record the repo's path so the source viewer can resolve doc citations.
            graph_store.upsert_repo(conn, repo, str(repo_path.resolve()))
        finally:
            conn.close()

        _job.state = "done"
        _job.message = (
            f"{len(to_index)} changed, {len(diff.unchanged)} unchanged, "
            f"{len(diff.deleted)} removed"
        )
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
