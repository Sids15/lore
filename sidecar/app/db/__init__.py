"""Embedded data stores for Lore.

Two local, server-less stores back the indexes:

* **SQLite** (:mod:`app.db.sqlite_store`) — the dependency/semantic graph plus the
  git-history tables (commits, blame, authorship).
* **LanceDB** (:mod:`app.db.lancedb_client`) — the vector store for embeddings.

Both live under the configured data directory and are created on first run.
"""
