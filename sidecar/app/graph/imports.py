"""Static import extraction → internal dependency edges.

For each source file we parse its import/use statements with tree-sitter and
resolve them to **other files in the same repository**. Resolution is done by
generating plausible candidate paths and keeping only those that actually exist
in the repo's file set — so external packages and unresolved targets simply
produce no edge (no false dependencies).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from app.ingest.ast_chunker import iter_source_files
from app.ingest.languages import get_parser, language_for_path

# Candidate file extensions per language family, in resolution priority order.
_PY_EXT = (".py", ".pyi")
_JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_RS_EXT = (".rs",)


@dataclass(frozen=True)
class ImportEdge:
    """A resolved internal dependency: ``src_file`` imports ``dst_file``."""

    src_file: str  # repo-relative POSIX path
    dst_file: str  # repo-relative POSIX path


def extract_graph(repo_root: Path) -> tuple[list[str], list[ImportEdge]]:
    """Return (nodes, edges) for a repo: one node per source file, import edges."""
    files = iter_source_files(repo_root)
    file_set = {f.relative_to(repo_root).as_posix() for f in files}

    edges: set[ImportEdge] = set()
    for path in files:
        language = language_for_path(path)
        if language is None:
            continue
        rel = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        root = get_parser(language).parse(bytes(source, "utf-8")).root_node
        for target in _resolve_file(language, root, rel, file_set):
            if target != rel:
                edges.add(ImportEdge(rel, target))

    return sorted(file_set), sorted(edges, key=lambda e: (e.src_file, e.dst_file))


def _resolve_file(language: str, root: Node, rel: str, file_set: set[str]) -> set[str]:
    if language == "python":
        return _python_imports(root, rel, file_set)
    if language in ("javascript", "typescript", "tsx"):
        return _js_imports(root, rel, file_set)
    if language == "rust":
        return _rust_imports(root, rel, file_set)
    return set()


def _first_existing(candidates: list[str], file_set: set[str]) -> str | None:
    for candidate in candidates:
        if candidate in file_set:
            return candidate
    return None


def _module_candidates(parts: list[str], extensions: tuple[str, ...]) -> list[str]:
    """Candidate files for a dotted/segmented module path (file or package)."""
    if not parts:
        return []
    base = "/".join(parts)
    out = [base + ext for ext in extensions]
    out += [f"{base}/__init__{ext}" for ext in extensions if ext in _PY_EXT]
    out += [f"{base}/index{ext}" for ext in extensions if ext in _JS_EXT]
    out += [f"{base}/mod{ext}" for ext in extensions if ext in _RS_EXT]
    return out


# ----------------------------- Python -----------------------------

def _python_imports(root: Node, rel: str, file_set: set[str]) -> set[str]:
    pkg_dir = posixpath.dirname(rel)
    found: set[str] = set()

    def text(node: Node) -> str:
        return node.text.decode("utf-8", errors="replace") if node.text else ""

    for node in _walk(root):
        if node.type == "import_statement":
            for child in node.named_children:
                name = child if child.type == "dotted_name" else child.child_by_field_name("name")
                if name is not None:
                    parts = text(name).split(".")
                    hit = _first_existing(_module_candidates(parts, _PY_EXT), file_set)
                    if hit:
                        found.add(hit)
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            base_parts, level = _python_from_base(module_node, text)
            # Resolve the module itself (e.g. `from app.config import x`).
            abs_parts = _python_apply_level(base_parts, level, pkg_dir)
            if abs_parts is not None:
                hit = _first_existing(_module_candidates(abs_parts, _PY_EXT), file_set)
                if hit:
                    found.add(hit)
                # Resolve imported names as submodules (e.g. `from app.db import x`).
                for name_node in node.named_children:
                    if name_node is module_node or name_node.type not in (
                        "dotted_name",
                        "aliased_import",
                    ):
                        continue
                    leaf = (
                        name_node
                        if name_node.type == "dotted_name"
                        else name_node.child_by_field_name("name")
                    )
                    if leaf is None:
                        continue
                    sub = _first_existing(
                        _module_candidates(abs_parts + [text(leaf)], _PY_EXT), file_set
                    )
                    if sub:
                        found.add(sub)
    return found


def _python_from_base(module_node: Node | None, text) -> tuple[list[str], int]:
    """Return (module parts, relative level) for an import-from module spec."""
    if module_node is None:
        return [], 0
    if module_node.type == "relative_import":
        raw = text(module_node)
        level = len(raw) - len(raw.lstrip("."))
        rest = raw[level:]
        return ([p for p in rest.split(".") if p], level)
    return (text(module_node).split("."), 0)


def _python_apply_level(parts: list[str], level: int, pkg_dir: str) -> list[str] | None:
    """Turn a (possibly relative) module path into a repo-root-relative part list."""
    if level == 0:
        return parts
    base = pkg_dir.split("/") if pkg_dir else []
    up = level - 1  # one dot = current package
    if up > len(base):
        return None
    base = base[: len(base) - up] if up else base
    return base + parts


# ----------------------------- JS / TS -----------------------------

def _js_imports(root: Node, rel: str, file_set: set[str]) -> set[str]:
    src_dir = posixpath.dirname(rel)
    found: set[str] = set()

    for node in _walk(root):
        spec: str | None = None
        if node.type == "import_statement":
            source = node.child_by_field_name("source")
            if source is not None and source.type == "string":
                spec = _string_value(source)
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.text and fn.text.decode() == "require":
                args = node.child_by_field_name("arguments")
                string_arg = (
                    next((c for c in args.named_children if c.type == "string"), None)
                    if args
                    else None
                )
                if string_arg is not None:
                    spec = _string_value(string_arg)

        if spec and spec.startswith("."):
            hit = _resolve_relative(src_dir, spec, _JS_EXT, file_set)
            if hit:
                found.add(hit)
    return found


def _string_value(node: Node) -> str:
    raw = node.text.decode("utf-8", errors="replace") if node.text else ""
    return raw.strip("\"'`")


def _resolve_relative(
    src_dir: str, spec: str, extensions: tuple[str, ...], file_set: set[str]
) -> str | None:
    joined = posixpath.normpath(posixpath.join(src_dir, spec))
    parts = [p for p in joined.split("/") if p not in ("", ".")]
    return _first_existing(_module_candidates(parts, extensions), file_set)


# ----------------------------- Rust -----------------------------

def _rust_imports(root: Node, rel: str, file_set: set[str]) -> set[str]:
    src_dir = posixpath.dirname(rel)
    found: set[str] = set()

    for node in _walk(root):
        if node.type != "use_declaration":
            continue
        argument = node.child_by_field_name("argument") or (
            node.named_children[0] if node.named_children else None
        )
        if argument is None:
            continue
        segments = _rust_path_segments(argument)
        for candidate in _rust_candidates(segments, src_dir):
            if candidate in file_set:
                found.add(candidate)
    return found


def _rust_path_segments(node: Node) -> list[str]:
    text = node.text.decode("utf-8", errors="replace") if node.text else ""
    head = text.split("{")[0]  # drop any use-list braces
    return [s for s in head.replace(" ", "").split("::") if s]


def _rust_candidates(segments: list[str], src_dir: str) -> list[str]:
    if not segments:
        return []
    first, *rest = segments
    # Drop the final segment (often an item/type name, not a module file).
    mod_parts = rest[:-1] if rest else []
    if first in ("crate",):
        bases = [["src"] + mod_parts, mod_parts]
    elif first in ("self", "super"):
        base = src_dir.split("/") if src_dir else []
        if first == "super" and base:
            base = base[:-1]
        bases = [base + mod_parts]
    elif first in ("std", "core", "alloc"):
        return []  # standard library — external
    else:
        base = src_dir.split("/") if src_dir else []
        bases = [base + [first] + mod_parts]

    candidates: list[str] = []
    for base in bases:
        candidates += _module_candidates([p for p in base if p], _RS_EXT)
    return candidates


# ----------------------------- shared -----------------------------

def _walk(node: Node):
    """Yield every node in the tree (pre-order)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)
