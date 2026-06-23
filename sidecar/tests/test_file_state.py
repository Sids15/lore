"""Tests for incremental-indexing file-hash bookkeeping (no network)."""

from __future__ import annotations

from app.db import sqlite_store
from app.ingest import file_state


def _conn(tmp_path):
    data = tmp_path / "data"
    sqlite_store.init_schema(data)
    return sqlite_store.connect(data)


def test_hash_file_is_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    h1 = file_state.hash_file(a)
    h2 = file_state.hash_file(a)
    assert h1 == h2

    a.write_text("hello!", encoding="utf-8")
    assert file_state.hash_file(a) != h1


def test_diff_classifies_new_changed_unchanged_deleted(tmp_path):
    conn = _conn(tmp_path)
    try:
        file_state.record_files(conn, "r", {"keep.py": "h1", "edit.py": "h2", "gone.py": "h3"})

        current = {"keep.py": "h1", "edit.py": "CHANGED", "added.py": "h4"}
        diff = file_state.diff_files(conn, "r", current)

        assert diff.new == ["added.py"]
        assert diff.changed == ["edit.py"]
        assert diff.unchanged == ["keep.py"]
        assert diff.deleted == ["gone.py"]
        assert set(diff.to_index) == {"added.py", "edit.py"}
        assert set(diff.to_delete) == {"edit.py", "gone.py"}
    finally:
        conn.close()


def test_record_then_rediff_is_all_unchanged(tmp_path):
    conn = _conn(tmp_path)
    try:
        hashes = {"a.py": "x", "b.py": "y"}
        file_state.record_files(conn, "r", hashes)
        diff = file_state.diff_files(conn, "r", hashes)
        assert diff.unchanged == ["a.py", "b.py"]
        assert diff.new == [] and diff.changed == [] and diff.deleted == []
    finally:
        conn.close()


def test_prune_removes_paths(tmp_path):
    conn = _conn(tmp_path)
    try:
        file_state.record_files(conn, "r", {"a.py": "x", "b.py": "y"})
        file_state.prune(conn, "r", ["a.py"])
        diff = file_state.diff_files(conn, "r", {"a.py": "x", "b.py": "y"})
        assert diff.new == ["a.py"]  # a.py was pruned, so it looks new again
        assert diff.unchanged == ["b.py"]
    finally:
        conn.close()


def test_repos_are_isolated(tmp_path):
    conn = _conn(tmp_path)
    try:
        file_state.record_files(conn, "one", {"a.py": "x"})
        file_state.record_files(conn, "two", {"a.py": "DIFFERENT"})
        diff = file_state.diff_files(conn, "one", {"a.py": "x"})
        assert diff.unchanged == ["a.py"]
    finally:
        conn.close()


def test_clear_repo(tmp_path):
    conn = _conn(tmp_path)
    try:
        file_state.record_files(conn, "r", {"a.py": "x", "b.py": "y"})
        file_state.clear_repo(conn, "r")
        diff = file_state.diff_files(conn, "r", {"a.py": "x"})
        assert diff.new == ["a.py"]
    finally:
        conn.close()
