"""Tests for the source-viewer endpoint (path-safe file windows)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import source as source_api
from app.config import Settings
from app.db import sqlite_store
from app.graph import graph_store


def _setup(tmp_path, *, lines=50):
    data = tmp_path / "data"
    sqlite_store.init_schema(data)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "\n".join(f"line{i}" for i in range(1, lines + 1)) + "\n", encoding="utf-8"
    )
    conn = sqlite_store.connect(data)
    try:
        graph_store.upsert_repo(conn, "repo", str(repo.resolve()))
    finally:
        conn.close()
    return data, repo


def _patch(monkeypatch, data, ctx=5):
    monkeypatch.setattr(
        source_api, "get_settings", lambda: Settings(data_dir=data, source_view_context=ctx)
    )


def test_returns_window_around_cited_range(tmp_path, monkeypatch):
    data, _ = _setup(tmp_path)
    _patch(monkeypatch, data, ctx=5)

    view = source_api.read_source(repo="repo", path="a.py", start=10, end=12)
    assert view.start_line == 10 and view.end_line == 12
    assert view.window_start == 5  # 10 - ctx(5)
    assert view.lines[0] == "line5"
    assert "line17" in view.lines  # 12 + ctx(5)


def test_window_clamps_at_file_start(tmp_path, monkeypatch):
    data, _ = _setup(tmp_path)
    _patch(monkeypatch, data, ctx=10)

    view = source_api.read_source(repo="repo", path="a.py", start=2, end=2)
    assert view.window_start == 1  # cannot go below line 1
    assert view.lines[0] == "line1"


def test_path_traversal_is_rejected(tmp_path, monkeypatch):
    data, _ = _setup(tmp_path)
    _patch(monkeypatch, data)
    with pytest.raises(HTTPException) as exc:
        source_api.read_source(repo="repo", path="../secret.txt", start=1, end=1)
    assert exc.value.status_code == 403


def test_unknown_repo_is_400(tmp_path, monkeypatch):
    data, _ = _setup(tmp_path)
    _patch(monkeypatch, data)
    with pytest.raises(HTTPException) as exc:
        source_api.read_source(repo="nope", path="a.py", start=1, end=1)
    assert exc.value.status_code == 400


def test_missing_file_is_404(tmp_path, monkeypatch):
    data, _ = _setup(tmp_path)
    _patch(monkeypatch, data)
    with pytest.raises(HTTPException) as exc:
        source_api.read_source(repo="repo", path="missing.py", start=1, end=1)
    assert exc.value.status_code == 404
