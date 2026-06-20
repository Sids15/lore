"""Client for the local Ollama runtime.

Phase 0 only needs a readiness probe: is Ollama reachable, and are the models
Lore depends on actually pulled? Generation and embedding calls are added in the
phases that use them.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel


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
