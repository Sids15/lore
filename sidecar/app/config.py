"""Application configuration for the Lore sidecar.

Settings are loaded (in order of precedence) from real environment variables,
then a local ``.env`` file, then the defaults below. Every variable is prefixed
``LORE_`` so it cannot collide with unrelated environment state. Nothing here is
hardcoded into call sites — code reads configuration via :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed runtime configuration for the sidecar."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LORE_",
        extra="ignore",
    )

    # Service identity.
    app_name: str = "Lore sidecar"
    version: str = "0.1.0"

    # HTTP server binding. Defaults to loopback so the sidecar is never exposed
    # off the local machine.
    host: str = "127.0.0.1"
    port: int = 8765

    # Directory for the embedded stores (LanceDB + SQLite). Created at runtime;
    # never committed to git.
    data_dir: Path = Path("data")

    # Browser origins allowed to call the sidecar (the Tauri/Vite frontend).
    cors_origins: list[str] = [
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "http://tauri.localhost",
    ]

    # Ollama runtime + model names. Used by later features; configurable here so
    # model choices are never baked into the code.
    ollama_url: str = "http://127.0.0.1:11434"
    generation_model: str = "qwen3:8b"
    embedding_model: str = "nomic-embed-text"
    reranker_model: str = "bge-reranker-base"

    @property
    def data_path(self) -> Path:
        """Absolute, user-expanded path to the data directory."""
        return self.data_dir.expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the resolved settings."""
    return Settings()
