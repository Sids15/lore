"""Client for the local Ollama runtime.

Phase 0 only needs a readiness probe: is Ollama reachable, and are the models
Lore depends on actually pulled? Generation and embedding calls are added in the
phases that use them.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel

# Defensive cleanup: some "thinking" models can emit <think>…</think> blocks.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class _ThinkStripper:
    """Strip ``<think>…</think>`` spans from a streamed token sequence.

    ``generate`` strips these with a regex over the whole response, but a stream
    delivers text in arbitrary pieces, so a tag can straddle two deltas. This
    stateful filter holds back a short tail that could be a partial tag and only
    emits text known to be outside a think block. ``think=False`` normally
    prevents these blocks, but reasoning models can still emit them.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"
    _KEEP = len("</think>") - 1  # longest partial tag we might need to hold back

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, delta: str) -> str:
        """Add a delta and return the text safe to emit now."""
        self._buf += delta
        out: list[str] = []
        while True:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    # Drop think content but keep a possible partial close tag.
                    self._buf = self._buf[-self._KEEP :]
                    break
                self._buf = self._buf[idx + len(self._CLOSE) :]
                self._in_think = False
            else:
                idx = self._buf.find(self._OPEN)
                if idx == -1:
                    # Emit all but a possible partial open tag at the tail.
                    if len(self._buf) > self._KEEP:
                        out.append(self._buf[: -self._KEEP])
                        self._buf = self._buf[-self._KEEP :]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self._OPEN) :]
                self._in_think = True
        return "".join(out)

    def flush(self) -> str:
        """Return any trailing buffered text (only if outside a think block)."""
        if self._in_think:
            return ""
        out, self._buf = self._buf, ""
        return out


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


async def generate_stream(
    base_url: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    timeout: float = 120.0,
    think: bool = False,
) -> AsyncIterator[str]:
    """Stream generated text token-by-token via Ollama's ``/api/generate``.

    Yields incremental answer deltas (already stripped of ``<think>`` spans) as
    they arrive. Raises ``httpx.HTTPError`` on transport/HTTP failure so callers
    can surface it.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": think,
    }
    if system:
        payload["system"] = system

    stripper = _ThinkStripper()
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue  # skip a malformed line rather than abort the stream
                piece = data.get("response", "")
                if piece:
                    text = stripper.feed(piece)
                    if text:
                        yield text
                if data.get("done"):
                    break

    tail = stripper.flush()
    if tail:
        yield tail


async def pull_model(base_url: str, model: str) -> AsyncIterator[dict]:
    """Stream an Ollama model pull, yielding each progress record.

    Proxies Ollama's ``/api/pull`` (``stream=True``). Each yielded dict is a raw
    Ollama line, e.g. ``{"status": "pulling manifest"}`` or
    ``{"status": "downloading …", "total": N, "completed": M}``; the final record
    has ``{"status": "success"}``. No timeout — model downloads run for minutes.
    Raises ``httpx.HTTPError`` on transport/HTTP failure.
    """
    url = f"{base_url.rstrip('/')}/api/pull"
    payload = {"name": model, "stream": True}
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue  # skip a malformed line rather than abort the pull
                yield data


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
