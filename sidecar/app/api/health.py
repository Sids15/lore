"""Health endpoint.

Reports a liveness signal plus the readiness of the embedded data stores so the
frontend can show an accurate system-status panel. Ollama readiness is added in
a later feature.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.db import lancedb_client, sqlite_store

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


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report sidecar liveness and data-store readiness."""
    settings = get_settings()
    data_path = settings.data_path

    databases = DatabasesHealth(
        sqlite=sqlite_store.is_ready(data_path),
        lancedb=lancedb_client.is_ready(data_path),
    )
    status = "ok" if (databases.sqlite and databases.lancedb) else "degraded"

    return HealthResponse(
        status=status,
        service=settings.app_name,
        version=settings.version,
        databases=databases,
    )
