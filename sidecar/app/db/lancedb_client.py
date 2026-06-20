"""LanceDB client: the embedded vector store for embeddings.

Phase 0 only establishes the on-disk store. The actual vector tables (code,
docs, and commit-summary namespaces) are created in the ingestion phases, once
the embedding dimensions are known.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import lancedb

if TYPE_CHECKING:  # pragma: no cover - typing only
    from lancedb.db import DBConnection

LANCEDB_DIRNAME = "lancedb"


def lancedb_path(data_dir: Path) -> Path:
    """Absolute path to the LanceDB store directory."""
    return data_dir / LANCEDB_DIRNAME


def connect(data_dir: Path) -> "DBConnection":
    """Open (creating if needed) the LanceDB store under the data directory."""
    path = lancedb_path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(path))


def init(data_dir: Path) -> None:
    """Ensure the LanceDB store exists on disk."""
    connect(data_dir)


def is_ready(data_dir: Path) -> bool:
    """Return True if the LanceDB store directory has been created."""
    return lancedb_path(data_dir).is_dir()
