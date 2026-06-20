"""Client for the local Ollama runtime.

Phase 0 only needs a readiness probe: is Ollama reachable, and are the models
Lore depends on actually pulled? Generation and embedding calls are added in the
phases that use them.
"""

from __future__ import annotations

import asyncio
import re

import httpx
from pydantic import BaseModel

# Defensive cleanup: some "thinking" models can emit <think>…</think> blocks.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaStatus(BaseModel):
    """Result of probing the Ollama runtime."""

    reachable: bool
    installed_models: list[str] = []
    missing_models: list[str] = []
    error: str | None = None


def _is_installed(installed_models: list[str], required: str) -> bool:
    """Return True if ``required`` is available among the installed models.

    Ollama reports tagged names (e.g. ``qwen3:8b`` or ``nomic-embed-text:latest``).
    A required name without an explicit tag matches any tag of the same base, and
    ``latest`` is treated as the default tag.
    """
    req_base, _, req_tag = required.partition(":")
    for name in installed_models:
        base, _, tag = name.partition(":")
        if base != req_base:
            continue
        if not req_tag or req_tag == tag or req_tag == "latest" or tag == "latest":
            return True
    return False


async def check(
    base_url: str,
    required_models: list[str],
    timeout: float = 3.0,
) -> OllamaStatus:
    """Probe Ollama for reachability and the presence of required models.

    Never raises: a connection failure is reported as ``reachable=False`` so the
    health endpoint can surface it without erroring.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        return OllamaStatus(
            reachable=False,
            missing_models=list(required_models),
            error=str(error),
        )

    installed = [model["name"] for model in payload.get("models", []) if "name" in model]
    missing = [m for m in required_models if not _is_installed(installed, m)]
    return OllamaStatus(
        reachable=True,
        installed_models=installed,
        missing_models=missing,
    )


async def generate(
    base_url: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
    think: bool = False,
) -> str:
    """Generate text from a prompt via Ollama's ``/api/generate`` endpoint.

    ``think=False`` keeps reasoning models (e.g. qwen3) from interleaving their
    chain-of-thought; any stray ``<think>`` block is stripped defensively.
    Raises ``httpx.HTTPError`` on transport/HTTP failure so callers can decide
    how to handle it.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    return _THINK_BLOCK.sub("", data.get("response", "")).strip()


async def embed_batch(
    base_url: str,
    model: str,
    texts: list[str],
    *,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Embed a list of texts in a single Ollama ``/api/embed`` call."""
    if not texts:
        return []
    url = f"{base_url.rstrip('/')}/api/embed"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json={"model": model, "input": texts})
        response.raise_for_status()
        data = response.json()
    return data.get("embeddings", [])


async def embed(base_url: str, model: str, text: str, *, timeout: float = 120.0) -> list[float]:
    """Embed a single text and return its vector."""
    vectors = await embed_batch(base_url, model, [text], timeout=timeout)
    return vectors[0]


async def embed_many(
    base_url: str,
    model: str,
    texts: list[str],
    *,
    concurrency: int = 4,
    batch_size: int = 16,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Embed many texts via concurrent, batched ``/api/embed`` calls.

    Results are returned in the same order as ``texts``.
    """
    if not texts:
        return []

    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    semaphore = asyncio.Semaphore(concurrency)

    async def run(batch: list[str]) -> list[list[float]]:
        async with semaphore:
            return await embed_batch(base_url, model, batch, timeout=timeout)

    results = await asyncio.gather(*(run(batch) for batch in batches))
    return [vector for batch in results for vector in batch]
