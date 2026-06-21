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
from app.db import lancedb_client, sqlite_store
from app.graph import graph_store, semantic
from app.graph.imports import extract_graph
from app.index import code_index
from app.index.code_index import CodeChunkRecord
from app.ingest.ast_chunker import chunk_repo
from app.ingest.enrich import EntityRelations, enrich_chunks
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
        # Ensure the embedded stores exist even when run outside the app lifespan.
        sqlite_store.init_schema(settings.data_path)

        chunks = chunk_repo(repo_path)
        _job.total = len(chunks)
        _job.message = "Indexing…"

        db = lancedb_client.connect(settings.data_path)
        code_index.delete_repo(db, repo_path.name)

        # Collected across batches to build the semantic graph after embedding.
        relations_by_chunk: dict[str, EntityRelations] = {}

        for batch in _batches(chunks, _BATCH_SIZE):
            try:
                enrichments = await enrich_chunks(batch, settings)
                texts = [e.embedding_text for e in enrichments]
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
                for chunk, enrichment in zip(batch, enrichments):
                    if enrichment.relations is not None:
                        relations_by_chunk[chunk.chunk_id] = enrichment.relations
            except (httpx.HTTPError, ValueError) as error:
                _job.errors.append(f"batch failed: {error}")
            finally:
                _job.processed += len(batch)

        # Rebuild the full-text index so keyword/hybrid search covers the new rows.
        code_index.ensure_fts_index(db, force=True)

        # Build the static dependency graph (deterministic, no LLM).
        _job.message = "Building dependency graph…"
        nodes, edges = extract_graph(repo_path)
        conn = sqlite_store.connect(settings.data_path)
        try:
            graph_store.replace_static_graph(conn, repo_path.name, nodes, edges)
            # Record the repo's path so architecture rules can be evaluated later.
            graph_store.upsert_repo(conn, repo_path.name, str(repo_path.resolve()))

            # Build the semantic graph from the LLM-extracted relationships.
            sem_edges: list = []
            if settings.semantic_enabled and relations_by_chunk:
                _job.message = "Extracting relationships…"
                sem_nodes, sem_edges = semantic.build_semantic_graph(chunks, relations_by_chunk)
                graph_store.replace_semantic_graph(conn, repo_path.name, sem_nodes, sem_edges)
        finally:
            conn.close()

        _job.state = "done"
        _job.message = (
            f"Indexed {_job.processed} chunks; {len(edges)} dependencies, "
            f"{len(sem_edges)} relationships"
        )
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
