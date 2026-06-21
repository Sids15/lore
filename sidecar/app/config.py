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

    # --- Code Index ingestion (Phase 1) ---
    # Contextual enrichment: prepend an LLM-written situating header per chunk.
    # The PRD's highest-leverage quality feature; disable for faster indexing.
    enrich_enabled: bool = True
    enrich_concurrency: int = 4

    # Semantic graph (Graph Layer B): the enrichment LLM call also extracts entity
    # relationships (calls / inherits / implements / intent) used to build it.
    semantic_enabled: bool = True

    # Embedding throughput and vector size (nomic-embed-text -> 768 dims).
    embed_concurrency: int = 4
    embedding_dim: int = 768

    # --- Retrieval (Phase 2) ---
    # Hybrid search (vector + LanceDB FTS, merged with RRF), then a cross-encoder
    # reranker re-scores the candidates down to the final set.
    fts_column: str = "enriched_text"
    rerank_candidates: int = 30  # hybrid candidates fed to the reranker
    retrieval_top_k: int = 8  # results returned after reranking
    answer_context_k: int = 6  # top chunks included in the LLM answer context
    grounding_enabled: bool = True  # second LLM pass that checks faithfulness
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-base"  # ONNX cross-encoder via fastembed

    # Where downloaded model files (e.g. the ONNX reranker) are cached. Defaults
    # to a "models" folder under the data dir so it persists across runs and stays
    # out of git (rather than a volatile temp directory).
    model_cache_dir: Path | None = None

    # --- Architecture graph (Phase 3) ---
    graph_max_cycles: int = 50  # cap on reported import cycles
    graph_max_nodes: int = 600  # safety cap on nodes sent to the visualization

    # Directory names skipped when walking a repository for source files.
    index_exclude_dirs: list[str] = [
        ".git",
        "node_modules",
        "target",
        ".venv",
        "venv",
        "dist",
        "build",
        "data",
        "__pycache__",
    ]

    @property
    def data_path(self) -> Path:
        """Absolute, user-expanded path to the data directory."""
        return self.data_dir.expanduser().resolve()

    @property
    def model_cache_path(self) -> Path:
        """Absolute path where downloaded model files are cached."""
        base = self.model_cache_dir if self.model_cache_dir is not None else self.data_path / "models"
        return Path(base).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the resolved settings."""
    return Settings()
