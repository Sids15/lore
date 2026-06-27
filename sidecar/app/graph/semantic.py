"""Build the semantic graph (Graph Layer B) from LLM-extracted relations.

The enrichment pass produces, per code entity, the names it references (calls,
extends, implements). Here we resolve those names to other entities in the repo
and emit typed edges. Resolution is approximate by design: a name is matched to
an entity in the **same file** first, then to a **unique** match elsewhere;
ambiguous or external names are skipped (no false edge).
"""

from __future__ import annotations

from app.graph.graph_store import SemanticEdge, SemanticNode
from app.ingest.ast_chunker import CodeChunk
from app.ingest.enrich import EntityRelations

_ENTITY_KINDS = {"function", "class", "method"}


def _clean_name(name: str) -> str:
    """Reduce a referenced name to a bare symbol (drop args and receivers)."""
    name = name.strip().split("(")[0].strip()
    for sep in (".", "::"):
        if sep in name:
            name = name.split(sep)[-1]
    return name


def _resolve(
    name: str, from_chunk: CodeChunk, index: dict[str, list[CodeChunk]]
) -> CodeChunk | None:
    key = _clean_name(name)
    candidates = index.get(key)
    if not candidates:
        return None
    same_file = [c for c in candidates if c.file_path == from_chunk.file_path]
    if same_file:
        return same_file[0]
    if len(candidates) == 1:
        return candidates[0]
    return None  # ambiguous across files -> skip


def build_semantic_graph(
    chunks: list[CodeChunk],
    relations_by_chunk: dict[str, EntityRelations],
) -> tuple[list[SemanticNode], list[SemanticEdge]]:
    """Return entity nodes and typed relationship edges for the semantic graph."""
    entities = [c for c in chunks if c.kind in _ENTITY_KINDS]

    index: dict[str, list[CodeChunk]] = {}
    for chunk in entities:
        index.setdefault(chunk.symbol, []).append(chunk)

    nodes = [
        SemanticNode(
            qualified_name=chunk.qualified_name,
            kind=chunk.kind,
            file_path=chunk.file_path,
            intent=(relations_by_chunk.get(chunk.chunk_id).intent
                    if relations_by_chunk.get(chunk.chunk_id) else ""),
        )
        for chunk in entities
    ]

    edge_set: set[tuple[str, str, str]] = set()
    for chunk in entities:
        relations = relations_by_chunk.get(chunk.chunk_id)
        if relations is None:
            continue
        for name in relations.calls:
            target = _resolve(name, chunk, index)
            if target and target.qualified_name != chunk.qualified_name:
                edge_set.add((chunk.qualified_name, target.qualified_name, "calls"))
        for name in relations.extends:
            target = _resolve(name, chunk, index)
            if target and target.qualified_name != chunk.qualified_name:
                edge_set.add((chunk.qualified_name, target.qualified_name, "inherits"))
        for name in relations.implements:
            target = _resolve(name, chunk, index)
            if target and target.qualified_name != chunk.qualified_name:
                edge_set.add((chunk.qualified_name, target.qualified_name, "implements"))

    edges = [SemanticEdge(src=s, dst=d, edge_type=t) for s, d, t in sorted(edge_set)]
    return nodes, edges
