"""Health endpoint.

Phase 0 returns a simple liveness signal. Later features extend this to report
the readiness of the embedded databases and the Ollama runtime, so the frontend
can show an accurate system-status panel.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Shape of the ``/health`` payload."""

    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the sidecar process is up and reachable."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
    )
