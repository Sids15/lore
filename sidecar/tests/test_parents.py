"""Tests for parent-chunk expansion (no network: the LanceDB fetch is stubbed)."""

from __future__ import annotations

from app.config import Settings
from app.query import parents
from app.retrieval.hybrid import RetrievedChunk


def _chunk(qualified_name: str, kind: str) -> RetrievedChunk:
    symbol = qualified_name.split("::")[-1]
    return RetrievedChunk(
        chunk_id=qualified_name,
        repo="r",
        file_path=qualified_name.split("::")[0],
        language="python",
        kind=kind,
        symbol=symbol,
        qualified_name=qualified_name,
        start_line=1,
        end_line=2,
        code="...",
        score=1.0,
    )


def _row(qualified_name: str, kind: str, code: str) -> dict:
    return {
        "qualified_name": qualified_name,
        "file_path": qualified_name.split("::")[0],
        "kind": kind,
        "symbol": qualified_name.split("::")[-1],
        "start_line": 1,
        "code": code,
    }


def _patch_fetch(monkeypatch, rows, *, capture=None):
    def fake_fetch(db, repo, names):
        if capture is not None:
            capture["names"] = names
            capture["repo"] = repo
        return rows

    monkeypatch.setattr(parents.lancedb_client, "connect", lambda path: None)
    monkeypatch.setattr(parents.code_index, "get_by_qualified_names", fake_fetch)


def test_disabled_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fetch must not run when disabled")

    monkeypatch.setattr(parents.code_index, "get_by_qualified_names", boom)
    out = parents.expand_parents(
        [_chunk("m.py::C.foo", "method")], Settings(parent_expansion_enabled=False)
    )
    assert out == []


def test_method_requests_class_and_module(monkeypatch):
    capture: dict = {}
    rows = [
        _row("m.py::C", "class", "class C:\n    x = 1"),
        _row("m.py::<module>", "module", "import os"),
    ]
    _patch_fetch(monkeypatch, rows, capture=capture)

    out = parents.expand_parents([_chunk("m.py::C.foo", "method")], Settings())

    # A method asks for its enclosing class and its file's module/imports.
    assert capture["names"] == ["m.py::C", "m.py::<module>"]
    assert capture["repo"] == "r"
    assert any("enclosing class C" in s for s in out)
    assert any("(imports)" in s and "import os" in s for s in out)


def test_function_requests_only_module(monkeypatch):
    capture: dict = {}
    _patch_fetch(monkeypatch, [_row("u.py::<module>", "module", "import sys")], capture=capture)

    parents.expand_parents([_chunk("u.py::bar", "function")], Settings())
    assert capture["names"] == ["u.py::<module>"]  # no class for a plain function


def test_target_already_in_chunks_is_dropped(monkeypatch):
    capture: dict = {}
    _patch_fetch(monkeypatch, [], capture=capture)

    # The class itself was retrieved, so don't request it again — only the module.
    chunks = [_chunk("m.py::C.foo", "method"), _chunk("m.py::C", "class")]
    parents.expand_parents(chunks, Settings())
    assert capture["names"] == ["m.py::<module>"]


def test_class_code_is_trimmed_to_header(monkeypatch):
    long_class = "class C:\n" + "\n".join(f"    line{i} = {i}" for i in range(20))
    _patch_fetch(monkeypatch, [_row("m.py::C", "class", long_class)])

    out = parents.expand_parents(
        [_chunk("m.py::C.foo", "method")],
        Settings(parent_header_max_lines=3, parent_context_max_chars=10000),
    )
    body = out[0]
    assert "line0 = 0" in body and "line1 = 1" in body
    assert "line5 = 5" not in body  # trimmed past the header
    assert body.endswith("…")


def test_char_budget_caps_total(monkeypatch):
    rows = [
        _row("m.py::C", "class", "class C: ..."),
        _row("m.py::<module>", "module", "x" * 500),
    ]
    _patch_fetch(monkeypatch, rows)

    out = parents.expand_parents(
        [_chunk("m.py::C.foo", "method")],
        Settings(parent_context_max_chars=60),
    )
    assert sum(len(s) for s in out) <= 60 + 1  # +1 for the truncation ellipsis


def test_fetch_error_fails_open(monkeypatch):
    monkeypatch.setattr(parents.lancedb_client, "connect", lambda path: None)

    def boom(db, repo, names):
        raise OSError("lancedb unavailable")

    monkeypatch.setattr(parents.code_index, "get_by_qualified_names", boom)
    assert parents.expand_parents([_chunk("m.py::C.foo", "method")], Settings()) == []
