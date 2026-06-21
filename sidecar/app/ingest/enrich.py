"""Contextual enrichment + semantic relationship extraction.

A single local-LLM call per chunk does double duty:

* **Enrichment** — a one/two-sentence *situating header* prepended to the code
  before embedding, so a chunk is retrievable by what it *does* (the PRD's
  highest-leverage retrieval improvement).
* **Semantic extraction** — the relationships the chunk participates in (which
  functions it **calls**, classes it **extends**/**implements**, and a short
  design **intent**), used to build the semantic graph (Graph Layer B).

Combining them keeps indexing to one LLM call per chunk. Everything is
best-effort: if the call fails or its JSON can't be parsed, we fall back to the
raw code / no relations so ingestion never blocks.
"""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.ingest.ast_chunker import CodeChunk
from app.llm import ollama_client
from app.llm.parsing import parse_json_object

_SUMMARY_SYSTEM = (
    "You write concise, factual descriptions of code for a search index. "
    "Respond with one or two sentences and no preamble, markdown, or code."
)

_SEMANTIC_SYSTEM = (
    "You analyze code and respond with ONLY a JSON object: "
    '{"summary": "<1-2 sentence description of what it does>", '
    '"calls": ["<functions/methods it calls>"], '
    '"extends": ["<base classes>"], '
    '"implements": ["<interfaces/traits>"], '
    '"intent": "<short design intent>"}. '
    "Use names exactly as they appear in the code. Use [] when none apply."
)


class EntityRelations(BaseModel):
    """Relationships extracted from a code entity (for the semantic graph)."""

    calls: list[str] = []
    extends: list[str] = []
    implements: list[str] = []
    intent: str = ""


class ChunkEnrichment(BaseModel):
    """Result of enriching one chunk: text to embed + (optional) relations."""

    embedding_text: str
    relations: EntityRelations | None = None


def _summary_prompt(chunk: CodeChunk) -> str:
    return (
        f"Describe what this {chunk.kind} `{chunk.symbol}` from `{chunk.file_path}` does and "
        f"the role it plays, in one or two sentences for a code search index. "
        f"Summarize its purpose; do not restate the code.\n\n"
        f"```{chunk.language}\n{chunk.code}\n```"
    )


def _semantic_prompt(chunk: CodeChunk) -> str:
    return (
        f"Analyze this {chunk.kind} `{chunk.symbol}` from `{chunk.file_path}`.\n\n"
        f"```{chunk.language}\n{chunk.code}\n```"
    )


def _compose(summary: str, chunk: CodeChunk) -> str:
    summary = summary.strip()
    return f"{summary}\n\n{chunk.code}" if summary else chunk.code


def _relations_from(data: dict) -> EntityRelations:
    def names(key: str) -> list[str]:
        value = data.get(key)
        return [str(v) for v in value] if isinstance(value, list) else []

    return EntityRelations(
        calls=names("calls"),
        extends=names("extends"),
        implements=names("implements"),
        intent=str(data.get("intent") or ""),
    )


async def enrich_chunk(chunk: CodeChunk, settings: Settings) -> ChunkEnrichment:
    """Enrich a single chunk. Never raises — failures fall back to raw code."""
    if not settings.enrich_enabled:
        return ChunkEnrichment(embedding_text=chunk.code)

    semantic = settings.semantic_enabled
    system = _SEMANTIC_SYSTEM if semantic else _SUMMARY_SYSTEM
    prompt = _semantic_prompt(chunk) if semantic else _summary_prompt(chunk)

    try:
        raw = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, prompt, system=system
        )
    except (httpx.HTTPError, ValueError):
        return ChunkEnrichment(embedding_text=chunk.code)

    if not semantic:
        return ChunkEnrichment(embedding_text=_compose(raw, chunk))

    data = parse_json_object(raw)
    if data is None:
        # JSON failed — still use the raw text as a header, but no relations.
        return ChunkEnrichment(embedding_text=_compose(raw, chunk))

    summary = str(data.get("summary") or "")
    return ChunkEnrichment(
        embedding_text=_compose(summary, chunk),
        relations=_relations_from(data),
    )


async def enrich_chunks(
    chunks: list[CodeChunk], settings: Settings
) -> list[ChunkEnrichment]:
    """Enrich many chunks concurrently, bounded by ``enrich_concurrency``.

    Returns results aligned 1:1 with the input chunks.
    """
    if not settings.enrich_enabled:
        return [ChunkEnrichment(embedding_text=chunk.code) for chunk in chunks]

    semaphore = asyncio.Semaphore(settings.enrich_concurrency)

    async def run(chunk: CodeChunk) -> ChunkEnrichment:
        async with semaphore:
            return await enrich_chunk(chunk, settings)

    return await asyncio.gather(*(run(chunk) for chunk in chunks))
