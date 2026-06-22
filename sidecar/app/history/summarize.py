"""LLM summarisation of commits.

The PRD's key decision: a raw diff is meaningless as an embedding, so each commit
is summarised into 2-3 human-readable sentences (what changed and why) — and the
*summary* is what gets embedded. Best-effort: on failure, fall back to the commit
message subject.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.history.git_walker import WalkedCommit
from app.llm import ollama_client

_SYSTEM = (
    "You summarise a git commit for a search index in 2-3 sentences: what changed "
    "and why. Be concrete and factual; no preamble, markdown, or code."
)


def _subject(commit: WalkedCommit) -> str:
    return commit.message.splitlines()[0] if commit.message else commit.sha[:7]


def _prompt(commit: WalkedCommit) -> str:
    files = ", ".join(path for path, _ in commit.files[:20])
    return (
        f"Commit message: {commit.message}\n"
        f"Files changed: {files}\n\n"
        f"Diff (truncated):\n{commit.diff}\n\n"
        "Summary:"
    )


async def summarise(commit: WalkedCommit, settings: Settings) -> str:
    """Summarise one commit; falls back to the message subject on failure."""
    try:
        text = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, _prompt(commit), system=_SYSTEM
        )
    except (httpx.HTTPError, ValueError):
        return _subject(commit)
    return text.strip() or _subject(commit)


async def summarise_many(commits: list[WalkedCommit], settings: Settings) -> list[str]:
    """Summarise commits concurrently (bounded), aligned 1:1 with the input."""
    semaphore = asyncio.Semaphore(settings.enrich_concurrency)

    async def run(commit: WalkedCommit) -> str:
        async with semaphore:
            return await summarise(commit, settings)

    return await asyncio.gather(*(run(c) for c in commits))
