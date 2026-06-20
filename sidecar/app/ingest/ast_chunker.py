"""AST-aware code chunking with tree-sitter.

Splits source files along natural boundaries — functions, classes/types, and
methods — instead of fixed-size windows, so each chunk is a semantically whole
unit. Every chunk carries enough metadata (file, language, symbol, line range)
to cite it precisely on retrieval. This pass is fully deterministic: no LLM, no
database, no network.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel
from tree_sitter import Node

from app.config import get_settings
from app.ingest.languages import SPECS, LanguageSpec, get_parser, language_for_path

# Chunk kinds, kept deliberately small. Type-like declarations (struct, enum,
# trait, interface) are recorded as "class".
ChunkKind = str  # one of: module | class | function | method


class CodeChunk(BaseModel):
    """A single unit of code with its provenance metadata."""

    chunk_id: str
    repo: str
    file_path: str  # POSIX, relative to the repo root
    language: str
    kind: ChunkKind
    symbol: str
    qualified_name: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    code: str


def _make_chunk_id(repo: str, file_path: str, qualified_name: str, start_line: int) -> str:
    """Stable id for a chunk so re-indexing the same code is idempotent."""
    raw = f"{repo}|{file_path}|{qualified_name}|{start_line}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _node_text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace") if node.text is not None else ""


def _node_name(node: Node) -> str | None:
    """Best-effort symbol name for a declaration node."""
    for field_name in ("name", "type"):
        child = node.child_by_field_name(field_name)
        if child is not None:
            return _node_text(child)
    for child in node.named_children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            return _node_text(child)
    return None


def _unwrap(node: Node, spec: LanguageSpec) -> Node:
    """Descend through wrapper nodes (decorators, `export`) to the real decl.

    The wrapped declaration is the last named child: for `decorated_definition`
    the leading children are decorators, and for `export_statement` the trailing
    child is the declaration being exported.
    """
    current = node
    while current.type in spec.unwrap_types and current.named_children:
        current = current.named_children[-1]
    return current


def _body_node(node: Node) -> Node | None:
    """Return the block/body container that holds a class's or impl's members."""
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for child in node.named_children:
        if child.type in {"block", "class_body", "declaration_list", "enum_body", "field_declaration_list"}:
            return child
    return None


def _arrow_name(node: Node, spec: LanguageSpec) -> str | None:
    """If a variable declaration assigns an arrow/function, return its name."""
    if node.type not in spec.arrow_decl_types:
        return None
    for declarator in node.named_children:
        if declarator.type != "variable_declarator":
            continue
        value = declarator.child_by_field_name("value")
        if value is not None and value.type in spec.arrow_value_types:
            name = declarator.child_by_field_name("name")
            return _node_text(name) if name is not None else None
    return None


def _build_chunk(
    *,
    outer: Node,
    repo: str,
    file_path: str,
    language: str,
    kind: ChunkKind,
    symbol: str,
    qualified_name: str,
) -> CodeChunk:
    start_line = outer.start_point[0] + 1
    end_line = outer.end_point[0] + 1
    return CodeChunk(
        chunk_id=_make_chunk_id(repo, file_path, qualified_name, start_line),
        repo=repo,
        file_path=file_path,
        language=language,
        kind=kind,
        symbol=symbol,
        qualified_name=qualified_name,
        start_line=start_line,
        end_line=end_line,
        code=_node_text(outer),
    )


def _method_chunks(
    container: Node,
    parent_symbol: str,
    *,
    repo: str,
    file_path: str,
    language: str,
    spec: LanguageSpec,
) -> list[CodeChunk]:
    """Emit one chunk per method inside a class/impl body."""
    body = _body_node(container)
    if body is None:
        return []
    chunks: list[CodeChunk] = []
    for member in body.named_children:
        real = _unwrap(member, spec)
        if real.type not in spec.method_types:
            continue
        name = _node_name(real) or "<anonymous>"
        chunks.append(
            _build_chunk(
                outer=member,
                repo=repo,
                file_path=file_path,
                language=language,
                kind="method",
                symbol=name,
                qualified_name=f"{file_path}::{parent_symbol}.{name}",
            )
        )
    return chunks


def chunk_source(source: str, *, repo: str, file_path: str, language: str) -> list[CodeChunk]:
    """Chunk already-loaded source text. Pure function — easy to unit test."""
    spec = SPECS[language]
    tree = get_parser(language).parse(bytes(source, "utf-8"))
    root = tree.root_node

    chunks: list[CodeChunk] = []
    module_nodes: list[Node] = []

    for node in root.named_children:
        real = _unwrap(node, spec)

        if real.type in spec.function_types:
            name = _node_name(real) or "<anonymous>"
            chunks.append(
                _build_chunk(
                    outer=node,
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    kind="function",
                    symbol=name,
                    qualified_name=f"{file_path}::{name}",
                )
            )
            continue

        if real.type in spec.class_types:
            name = _node_name(real) or "<anonymous>"
            chunks.append(
                _build_chunk(
                    outer=node,
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    kind="class",
                    symbol=name,
                    qualified_name=f"{file_path}::{name}",
                )
            )
            chunks.extend(
                _method_chunks(
                    real, name, repo=repo, file_path=file_path, language=language, spec=spec
                )
            )
            continue

        if real.type in spec.impl_types:
            name = _node_name(real) or "<impl>"
            chunks.extend(
                _method_chunks(
                    real, name, repo=repo, file_path=file_path, language=language, spec=spec
                )
            )
            continue

        arrow_name = _arrow_name(real, spec)
        if arrow_name is not None:
            chunks.append(
                _build_chunk(
                    outer=node,
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    kind="function",
                    symbol=arrow_name,
                    qualified_name=f"{file_path}::{arrow_name}",
                )
            )
            continue

        module_nodes.append(node)

    module_chunk = _module_chunk(
        module_nodes, repo=repo, file_path=file_path, language=language
    )
    if module_chunk is not None:
        chunks.insert(0, module_chunk)

    return chunks


def _module_chunk(
    nodes: list[Node], *, repo: str, file_path: str, language: str
) -> CodeChunk | None:
    """Combine leftover top-level statements (imports, constants) into one chunk."""
    if not nodes:
        return None
    code = "\n".join(_node_text(n) for n in nodes)
    if not code.strip():
        return None
    start_line = nodes[0].start_point[0] + 1
    end_line = nodes[-1].end_point[0] + 1
    symbol = Path(file_path).name
    qualified_name = f"{file_path}::<module>"
    return CodeChunk(
        chunk_id=_make_chunk_id(repo, file_path, qualified_name, start_line),
        repo=repo,
        file_path=file_path,
        language=language,
        kind="module",
        symbol=symbol,
        qualified_name=qualified_name,
        start_line=start_line,
        end_line=end_line,
        code=code,
    )


def chunk_file(path: Path, repo_root: Path) -> list[CodeChunk]:
    """Chunk a single file on disk. Returns [] for unsupported file types."""
    language = language_for_path(path)
    if language is None:
        return []
    source = path.read_text(encoding="utf-8", errors="replace")
    file_path = path.relative_to(repo_root).as_posix()
    repo = repo_root.name
    return chunk_source(source, repo=repo, file_path=file_path, language=language)


def iter_source_files(repo_root: Path) -> list[Path]:
    """List supported source files under a repo, skipping excluded directories."""
    exclude = set(get_settings().index_exclude_dirs)
    results: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in exclude for part in path.relative_to(repo_root).parts[:-1]):
            continue
        if language_for_path(path) is not None:
            results.append(path)
    return results


def chunk_repo(repo_root: Path) -> list[CodeChunk]:
    """Chunk every supported source file in a repository."""
    chunks: list[CodeChunk] = []
    for file_path in iter_source_files(repo_root):
        chunks.extend(chunk_file(file_path, repo_root))
    return chunks
