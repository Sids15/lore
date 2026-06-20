"""Contextual enrichment — the PRD's highest-leverage retrieval improvement.

Each code chunk is given a one- or two-sentence *situating header* written by the
local LLM (e.g. "This function refreshes the auth token and is called from the
Express middleware."). The header is prepended to the code before embedding, so a
chunk is retrievable by what it *does*, not only by the identifiers it contains.

Enrichment is best-effort: if it is disabled or a model call fails, the raw code
is used instead so ingestion never blocks.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.ingest.ast_chunker import CodeChunk
from app.llm import ollama_client

_SYSTEM_PROMPT = (
    "You write concise, factual descriptions of code for a search index. "
    "Respond with one or two sentences and no preamble, markdown, or code."
)


def _build_prompt(chunk: CodeChunk) -> str:
    return (
        f"Describe what this {chunk.kind} `{chunk.symbol}` from `{chunk.file_path}` does and "
        f"the role it plays, in one or two sentences for a code search index. "
        f"Summarize its purpose; do not restate the code.\n\n"
        f"```{chunk.language}\n{chunk.code}\n```"
    )


def _compose(header: str, chunk: CodeChunk) -> str:
    header = header.strip()
    return f"{header}\n\n{chunk.code}" if header else chunk.code


async def enrich_chunk(chunk: CodeChunk, settings: Settings) -> str:
    """Return the chunk's embedding text: situating header + code, or just code.

    Never raises — failures fall back to the raw code.
    """
    if not settings.enrich_enabled:
        return chunk.code
    try:
        header = await ollama_client.generate(
            settings.ollama_url,
            settings.generation_model,
            _build_prompt(chunk),
            system=_SYSTEM_PROMPT,
        )
    except (httpx.HTTPError, ValueError):
        return chunk.code
    return _compose(header, chunk)


async def enrich_chunks(chunks: list[CodeChunk], settings: Settings) -> list[str]:
    """Enrich many chunks concurrently, bounded by ``enrich_concurrency``.

    Returns embedding texts aligned 1:1 with the input chunks.
    """
    if not settings.enrich_enabled:
        return [chunk.code for chunk in chunks]

    semaphore = asyncio.Semaphore(settings.enrich_concurrency)

    async def run(chunk: CodeChunk) -> str:
        async with semaphore:
            return await enrich_chunk(chunk, settings)

    return await asyncio.gather(*(run(chunk) for chunk in chunks))
