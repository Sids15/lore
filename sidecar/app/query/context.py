"""Routed context assembly (GraphRAG).

Given the router's decision, gather the right material for the answer: code
chunks via hybrid retrieval, plus — for relational/architectural questions —
facts from the dependency and semantic graphs (callers/callees, import cycles,
most-depended-on modules). Combining vector retrieval with graph traversal is the
"GraphRAG" step from the PRD roadmap.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings
from app.db import sqlite_store
from app.graph import analysis, graph_store
from app.query.router import RouteDecision
from app.retrieval import hybrid
from app.retrieval.hybrid import RetrievedChunk

_GRAPH_SEEDS = 4  # how many top chunks to expand into graph neighbours


class RetrievalBundle(BaseModel):
    """Everything gathered for an answer: code chunks + graph facts."""

    chunks: list[RetrievedChunk]
    graph_notes: list[str] = []
    graph_used: bool = False


def _short(name: str) -> str:
    if "::" in name:
        return name.split("::", 1)[1]
    return name.rsplit("/", 1)[-1]


def _adjacency(edges: list[tuple[str, str]]) -> tuple[dict, dict]:
    out_adj: dict[str, list[str]] = {}
    in_adj: dict[str, list[str]] = {}
    for src, dst in edges:
        out_adj.setdefault(src, []).append(dst)
        in_adj.setdefault(dst, []).append(src)
    return out_adj, in_adj


def _graph_context(
    chunks: list[RetrievedChunk], categories: set[str], settings: Settings
) -> list[str]:
    """Build short, human-readable graph facts relevant to the question."""
    repo = chunks[0].repo if chunks else None
    notes: list[str] = []
    conn = sqlite_store.connect(settings.data_path)
    try:
        if "relational" in categories and chunks:
            semantic = graph_store.load_graph(conn, repo, "semantic")
            out_adj, in_adj = _adjacency(semantic.edges)
            for chunk in chunks[:_GRAPH_SEEDS]:
                qn = chunk.qualified_name
                for callee in out_adj.get(qn, [])[:3]:
                    notes.append(f"{_short(qn)} calls {_short(callee)}")
                for caller in in_adj.get(qn, [])[:3]:
                    notes.append(f"{_short(caller)} calls {_short(qn)}")

        if "architectural" in categories:
            static = graph_store.load_graph(conn, repo, "static")
            for cycle in analysis.find_cycles(static, settings.graph_max_cycles)[:3]:
                notes.append("Circular dependency: " + " -> ".join(_short(n) for n in cycle))
            stats = analysis.degree_stats(static, top=3)
            top = ", ".join(
                f"{_short(r['file'])} ({r['in_degree']})" for r in stats["most_depended_on"]
            )
            if top:
                notes.append(f"Most depended-on modules: {top}")
    finally:
        conn.close()

    # De-duplicate (preserve order) and cap.
    seen: set[str] = set()
    unique = [n for n in notes if not (n in seen or seen.add(n))]
    return unique[: settings.graph_context_neighbours]


async def gather(
    question: str,
    route: RouteDecision,
    settings: Settings,
    *,
    broaden: bool = False,
    k: int | None = None,
) -> RetrievalBundle:
    """Gather code + graph context for a question, per its route."""
    if route.trivial and not broaden:
        return RetrievalBundle(chunks=[])

    base_k = k or settings.retrieval_top_k
    effective_k = base_k * (settings.correction_k_multiplier if broaden else 1)
    chunks = await hybrid.retrieve(question, k=effective_k, settings=settings)

    categories = set(route.categories)
    if broaden:  # a correction pass casts a wider net, including the graph
        categories |= {"relational", "architectural"}

    notes: list[str] = []
    if settings.graphrag_enabled and categories & {"relational", "architectural"}:
        notes = _graph_context(chunks, categories, settings)
    if "historical" in route.categories:
        notes = notes + ["Git-history search is not available yet (coming in a later phase)."]

    return RetrievalBundle(
        chunks=chunks[: settings.answer_context_k],
        graph_notes=notes,
        graph_used=bool(notes),
    )


def format_context(bundle: RetrievalBundle) -> str:
    """Render the bundle into a single prompt context string."""
    blocks = [
        f"[{i}] {c.file_path}:{c.start_line}-{c.end_line} ({c.kind} {c.symbol})\n{c.code}"
        for i, c in enumerate(bundle.chunks, start=1)
    ]
    code = "\n\n".join(blocks)
    if bundle.graph_notes:
        related = "\n".join(f"- {n}" for n in bundle.graph_notes)
        related_block = f"Related (from the code graph):\n{related}"
        return f"{code}\n\n{related_block}" if code else related_block
    return code
