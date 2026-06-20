"""Health endpoint.

Reports a liveness signal plus the readiness of the embedded data stores and the
Ollama runtime, so the frontend can show an accurate system-status panel and tell
the user exactly what (if anything) needs fixing.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client, sqlite_store
from app.llm import ollama_client
from app.llm.ollama_client import OllamaStatus

router = APIRouter(tags=["health"])


class DatabasesHealth(BaseModel):
    """Readiness of each embedded store."""

    sqlite: bool
    lancedb: bool


class HealthResponse(BaseModel):
    """Shape of the ``/health`` payload."""

    status: str
    service: str
    version: str
    databases: DatabasesHealth
    ollama: OllamaStatus


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report sidecar liveness, data-store readiness, and Ollama status."""
    settings = get_settings()
    data_path = settings.data_path

    databases = DatabasesHealth(
        sqlite=sqlite_store.is_ready(data_path),
        lancedb=lancedb_client.is_ready(data_path),
    )

    ollama = await ollama_client.check(
        settings.ollama_url,
        required_models=[settings.generation_model, settings.embedding_model],
    )

    healthy = (
        databases.sqlite
        and databases.lancedb
        and ollama.reachable
        and not ollama.missing_models
    )

    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.app_name,
        version=settings.version,
        databases=databases,
        ollama=ollama,
    )
