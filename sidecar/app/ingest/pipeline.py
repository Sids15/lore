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
from app.ingest import file_state, relation_store
from app.ingest.ast_chunker import chunk_repo, iter_source_files
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


async def index_repo(repo_path: Path, *, force: bool = False) -> IndexJob:
    """Index a repository's code into LanceDB, updating the job status as it goes.

    Incremental by default: only new/changed files are re-enriched and re-embedded;
    deleted files are pruned. The static graph is rebuilt fully every run (cheap,
    deterministic) and the semantic graph is rebuilt from stored (unchanged) +
    freshly-extracted (changed) relations so untouched files keep their edges.
    ``force=True`` does a full wipe-and-rebuild.
    """
    global _job
    settings = get_settings()
    repo = repo_path.name
    _job = IndexJob(state="running", repo=repo, message="Scanning files…")

    try:
        # Ensure the embedded stores exist even when run outside the app lifespan.
        sqlite_store.init_schema(settings.data_path)

        # Chunk every file (cheap, deterministic) and hash the source files.
        chunks = chunk_repo(repo_path)
        current = file_state.hash_files(repo_path, iter_source_files(repo_path))

        db = lancedb_client.connect(settings.data_path)
        conn = sqlite_store.connect(settings.data_path)
        try:
            if force:
                code_index.delete_repo(db, repo)
                file_state.clear_repo(conn, repo)
                relation_store.clear_repo(conn, repo)

            diff = file_state.diff_files(conn, repo, current)
            to_index = set(diff.to_index)
            to_delete = [] if force else diff.to_delete

            # Clear stale chunks + relations for changed and deleted files.
            code_index.delete_files(db, repo, to_delete)
            relation_store.delete_files(conn, repo, to_delete)

            chunks_to_index = [c for c in chunks if c.file_path in to_index]
            _job.total = len(chunks_to_index)
            _job.message = "Indexing…"

            # Freshly-extracted relations for the changed chunks (persisted below).
            fresh: dict[str, EntityRelations] = {}
            file_by_chunk: dict[str, str] = {}

            for batch in _batches(chunks_to_index, _BATCH_SIZE):
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
                        for chunk, text, vector in zip(batch, texts, vectors, strict=False)
                    ]
                    code_index.upsert(db, records)
                    for chunk, enrichment in zip(batch, enrichments, strict=False):
                        if enrichment.relations is not None:
                            fresh[chunk.chunk_id] = enrichment.relations
                            file_by_chunk[chunk.chunk_id] = chunk.file_path
                except (httpx.HTTPError, ValueError) as error:
                    _job.errors.append(f"batch failed: {error}")
                finally:
                    _job.processed += len(batch)

            # Rebuild the full-text index when rows changed.
            if chunks_to_index or to_delete:
                code_index.ensure_fts_index(db, force=True)

            # Persist the fresh relations, then load the complete (merged) set so
            # the semantic graph keeps edges for unchanged files.
            relation_store.save_relations(conn, repo, fresh, file_by_chunk)
            relations_by_chunk = relation_store.load_relations(conn, repo)

            # Static dependency graph: full deterministic rebuild (no LLM).
            _job.message = "Building dependency graph…"
            nodes, edges = extract_graph(repo_path)
            graph_store.replace_static_graph(conn, repo, nodes, edges)
            # Record the repo's path so architecture rules can be evaluated later.
            graph_store.upsert_repo(conn, repo, str(repo_path.resolve()))

            # Semantic graph: rebuilt from all chunks + the merged relations.
            sem_edges: list = []
            if settings.semantic_enabled and relations_by_chunk:
                _job.message = "Extracting relationships…"
                sem_nodes, sem_edges = semantic.build_semantic_graph(chunks, relations_by_chunk)
                graph_store.replace_semantic_graph(conn, repo, sem_nodes, sem_edges)

            # Record the new hashes and drop deleted files from the index.
            file_state.record_files(conn, repo, current)
            file_state.prune(conn, repo, diff.deleted)
        finally:
            conn.close()

        _job.state = "done"
        _job.message = (
            f"{len(to_index)} changed, {len(diff.unchanged)} unchanged, "
            f"{len(diff.deleted)} removed; {len(edges)} dependencies, "
            f"{len(sem_edges)} relationships"
        )
        if _job.errors:
            _job.message += f" ({len(_job.errors)} batch error(s))"
    except Exception as error:  # noqa: BLE001 - report any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
