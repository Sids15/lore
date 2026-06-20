"""Tests for the tree-sitter AST chunker."""

from __future__ import annotations

from app.ingest.ast_chunker import chunk_source


def _by_kind(chunks, kind):
    return [c for c in chunks if c.kind == kind]


def _symbols(chunks):
    return {c.symbol for c in chunks}


def test_python_functions_classes_and_methods():
    source = (
        "import os\n"
        "\n"
        "CONST = 1\n"
        "\n"
        "@decorator\n"
        "def top_level(x):\n"
        "    return x\n"
        "\n"
        "class Service:\n"
        "    def method_a(self):\n"
        "        return 1\n"
        "\n"
        "    def method_b(self):\n"
        "        return 2\n"
    )
    chunks = chunk_source(source, repo="r", file_path="svc.py", language="python")

    assert _by_kind(chunks, "module"), "imports/constants should form a module chunk"
    assert "top_level" in _symbols(chunks)
    assert "Service" in _symbols(_by_kind(chunks, "class"))
    method_symbols = _symbols(_by_kind(chunks, "method"))
    assert {"method_a", "method_b"} <= method_symbols

    # The decorated function chunk must include the decorator line.
    fn = next(c for c in chunks if c.symbol == "top_level")
    assert fn.code.startswith("@decorator")
    assert fn.start_line <= fn.end_line


def test_python_line_ranges_are_one_based():
    source = "def a():\n    return 1\n"
    [chunk] = [c for c in chunk_source(source, repo="r", file_path="a.py", language="python") if c.kind == "function"]
    assert chunk.start_line == 1
    assert chunk.end_line == 2


def test_typescript_exports_and_arrow_functions():
    source = (
        'import {x} from "y";\n'
        "export function declared(a: number) { return a; }\n"
        "export const arrow = (a: number) => a + 1;\n"
        "export class Widget { render() { return null; } }\n"
        "interface Shape { sides: number; }\n"
    )
    chunks = chunk_source(source, repo="r", file_path="ui.ts", language="typescript")
    symbols = _symbols(chunks)

    assert "declared" in symbols  # exported function unwrapped
    assert "arrow" in symbols  # arrow const detected as a function
    assert "Widget" in _symbols(_by_kind(chunks, "class"))
    assert "render" in _symbols(_by_kind(chunks, "method"))
    assert "Shape" in symbols  # interface recorded as a class-like chunk


def test_rust_functions_structs_and_impl_methods():
    source = (
        "use std::fmt;\n"
        "pub fn free_fn(x: i32) -> i32 { x }\n"
        "struct Point { x: i32 }\n"
        "impl Point {\n"
        "    fn distance(&self) -> i32 { self.x }\n"
        "}\n"
    )
    chunks = chunk_source(source, repo="r", file_path="geo.rs", language="rust")

    assert "free_fn" in _symbols(_by_kind(chunks, "function"))
    assert "Point" in _symbols(_by_kind(chunks, "class"))
    distance = next((c for c in chunks if c.symbol == "distance"), None)
    assert distance is not None and distance.kind == "method"
    assert distance.qualified_name.endswith("Point.distance")


def test_unsupported_returns_no_chunks_via_chunk_source_contract():
    # chunk_source requires a known language; the file-level guard lives in
    # chunk_file/language_for_path, exercised here for completeness.
    from app.ingest.languages import language_for_path

    assert language_for_path("notes.txt") is None
    assert language_for_path("main.py") == "python"
    assert language_for_path("app.tsx") == "tsx"


def test_chunk_ids_are_stable_and_unique():
    source = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    first = chunk_source(source, repo="r", file_path="m.py", language="python")
    second = chunk_source(source, repo="r", file_path="m.py", language="python")

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]  # stable
    assert len({c.chunk_id for c in first}) == len(first)  # unique
