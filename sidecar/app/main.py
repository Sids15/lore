"""Lore sidecar entry point.

Creates the FastAPI application, enables CORS for the desktop frontend, and
registers the route modules. Run in development with::

    python -m uvicorn app.main:app --reload --port 8765
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import parent_watchdog
from app.api import graph, health, index, query
from app.config import get_settings
from app.db import lancedb_client, sqlite_store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the embedded data stores before serving requests."""
    # Shut down if the parent (Tauri shell) dies, so we never orphan the port.
    parent_watchdog.start()
    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    sqlite_store.init_schema(settings.data_path)
    lancedb_client.init(settings.data_path)
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

    # Allow only the known frontend origins to call the sidecar.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(index.router)
    app.include_router(query.router)
    app.include_router(graph.router)
    return app


app = create_app()
