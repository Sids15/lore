"""Language registry for AST chunking.

Maps file extensions to languages and describes, per language, which tree-sitter
node types represent functions, classes/types, and methods. Parsers are built
lazily from the official per-language grammar packages and cached.

Adding a language is a matter of registering its grammar capsule, a
:class:`LanguageSpec`, and its file extensions — no chunker changes required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_rust
import tree_sitter_typescript
from tree_sitter import Language, Parser


@dataclass(frozen=True)
class LanguageSpec:
    """Node-type classification rules for one language."""

    name: str
    # Top-level node types that are standalone functions.
    function_types: frozenset[str]
    # Container types whose name we keep and whose body holds methods
    # (classes plus type-like declarations: struct/enum/trait/interface).
    class_types: frozenset[str]
    # Method node types found inside class/impl bodies.
    method_types: frozenset[str]
    # Containers that hold methods but are not themselves emitted as a chunk
    # (Rust `impl` blocks).
    impl_types: frozenset[str] = field(default_factory=frozenset)
    # Wrapper nodes to unwrap to reach the real declaration
    # (Python `decorated_definition`, TS/JS `export_statement`).
    unwrap_types: frozenset[str] = field(default_factory=frozenset)
    # Variable-declaration node types that may hold an arrow/function expression.
    arrow_decl_types: frozenset[str] = field(default_factory=frozenset)
    # Inner expression types that mark an arrow-declared function.
    arrow_value_types: frozenset[str] = field(default_factory=frozenset)


# Grammar capsule factories (called once per language, then cached as a Language).
_LANGUAGE_CAPSULES = {
    "python": tree_sitter_python.language,
    "javascript": tree_sitter_javascript.language,
    "typescript": tree_sitter_typescript.language_typescript,
    "tsx": tree_sitter_typescript.language_tsx,
    "rust": tree_sitter_rust.language,
}

_JS_TS_COMMON = {
    "function_types": frozenset({"function_declaration", "generator_function_declaration"}),
    "method_types": frozenset({"method_definition"}),
    "unwrap_types": frozenset({"export_statement"}),
    "arrow_decl_types": frozenset({"lexical_declaration", "variable_declaration"}),
    "arrow_value_types": frozenset({"arrow_function", "function", "function_expression"}),
}

SPECS: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        name="python",
        function_types=frozenset({"function_definition"}),
        class_types=frozenset({"class_definition"}),
        method_types=frozenset({"function_definition"}),
        unwrap_types=frozenset({"decorated_definition"}),
    ),
    "javascript": LanguageSpec(
        name="javascript",
        class_types=frozenset({"class_declaration"}),
        **_JS_TS_COMMON,
    ),
    "typescript": LanguageSpec(
        name="typescript",
        class_types=frozenset(
            {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
            }
        ),
        **_JS_TS_COMMON,
    ),
    "tsx": LanguageSpec(
        name="tsx",
        class_types=frozenset(
            {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
            }
        ),
        **_JS_TS_COMMON,
    ),
    "rust": LanguageSpec(
        name="rust",
        function_types=frozenset({"function_item"}),
        class_types=frozenset({"struct_item", "enum_item", "trait_item", "union_item"}),
        method_types=frozenset({"function_item"}),
        impl_types=frozenset({"impl_item"}),
    ),
}

# File extension -> language name.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
}


@cache
def get_parser(language: str) -> Parser:
    """Return a cached tree-sitter parser for the given language name."""
    capsule_factory = _LANGUAGE_CAPSULES[language]
    return Parser(Language(capsule_factory()))


def language_for_path(path: Path | str) -> str | None:
    """Return the language name for a file path, or None if unsupported."""
    suffix = Path(path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(suffix)
