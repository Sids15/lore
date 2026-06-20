"""Lore sidecar entry point.

Creates the FastAPI application, enables CORS for the desktop frontend, and
registers the route modules. Run in development with::

    python -m uvicorn app.main:app --reload --port 8765
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import get_settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(title=settings.app_name, version=settings.version)

    # Allow only the known frontend origins to call the sidecar.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    return app


app = create_app()
