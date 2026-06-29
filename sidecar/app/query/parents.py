"""Parent-chunk expansion: attach each retrieved chunk's enclosing context.

Chunks are function/method-sized, so a retrieved method is shown to the LLM
without its class's fields/base-class/docstring, and any chunk without its file's
imports. This pulls that enclosing context — the method's class header and the
file's module (imports/top-level constants) — as extra prompt context. It's a
couple of LanceDB metadata lookups over data already indexed: no LLM call, no
re-embedding. Fails open (a lookup error just yields less/no extra context) so it
can never break a query.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.db import lancedb_client
from app.index import code_index
from app.retrieval.hybrid import RetrievedChunk

_MODULE_SUFFIX = "::<module>"


def _module_qn(file_path: str) -> str:
    return f"{file_path}{_MODULE_SUFFIX}"


def _parent_class_qn(qualified_name: str) -> str | None:
    """Enclosing class for a method qn ``file::Class.method`` -> ``file::Class``."""
    file_part, _, symbol_part = qualified_name.partition("::")
    if not symbol_part or "." not in symbol_part:
        return None
    return f"{file_part}::{symbol_part.rsplit('.', 1)[0]}"


def _trim_lines(code: str, max_lines: int) -> str:
    """Keep the first ``max_lines`` lines (a class header, not its methods)."""
    lines = code.splitlines()
    if len(lines) <= max_lines:
        return code
    return "\n".join(lines[:max_lines]) + "\n…"


def _render(row: dict, settings: Settings) -> str:
    loc = f"{row['file_path']}:{row['start_line']}"
    if row.get("kind") == "module":
        return f"[{loc} (imports)]\n{row['code']}"
    body = _trim_lines(row["code"], settings.parent_header_max_lines)
    return f"[{loc} (enclosing class {row['symbol']})]\n{body}"


def expand_parents(chunks: list[RetrievedChunk], settings: Settings) -> list[str]:
    """Return labelled enclosing-context snippets for the retrieved ``chunks``.

    For each chunk: the file's module/imports chunk, plus (for methods) the
    enclosing class. Names already present among ``chunks`` are skipped so a
    source isn't duplicated. The total is capped at ``parent_context_max_chars``.
    """
    if not settings.parent_expansion_enabled or not chunks:
        return []

    have = {chunk.qualified_name for chunk in chunks}
    targets: list[str] = []

    def _want(name: str | None) -> None:
        if name and name not in have and name not in targets:
            targets.append(name)

    for chunk in chunks:
        if chunk.kind == "method":
            _want(_parent_class_qn(chunk.qualified_name))
        _want(_module_qn(chunk.file_path))

    if not targets:
        return []

    try:
        db = lancedb_client.connect(settings.data_path)
        rows = code_index.get_by_qualified_names(db, chunks[0].repo, targets)
    except (httpx.HTTPError, ValueError, OSError):
        return []

    # Preserve the requested order (rows come back unordered).
    by_name = {row["qualified_name"]: row for row in rows}

    snippets: list[str] = []
    budget = settings.parent_context_max_chars
    used = 0
    for name in targets:
        row = by_name.get(name)
        if row is None:
            continue
        snippet = _render(row, settings)
        if used + len(snippet) > budget:
            remaining = budget - used
            if remaining > 0:
                snippets.append(snippet[:remaining] + "…")
            break
        snippets.append(snippet)
        used += len(snippet)
    return snippets
