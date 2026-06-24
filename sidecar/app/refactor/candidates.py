"""Deterministic detection of refactoring candidates.

Surfaces a repo's worst structural problems from signals Lore already computes —
circular dependencies, coupling hubs (god modules), and architecture-rule
violations — with no LLM. Each candidate is grounded in concrete files so a
suggestion can be requested for it later.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.graph import analysis, graph_store, rules


class RefactorCandidate(BaseModel):
    """A structural problem worth refactoring."""

    id: str
    kind: str  # "cycle" | "hub" | "violation"
    severity: str  # "high" | "medium" | "low"
    title: str
    summary: str
    files: list[str] = []
    symbols: list[str] = []


def _candidate_id(kind: str, files: list[str]) -> str:
    raw = kind + "|" + "|".join(sorted(files))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _cycle_candidates(data: graph_store.GraphData, settings: Settings) -> list[RefactorCandidate]:
    out: list[RefactorCandidate] = []
    for cycle in analysis.find_cycles(data, settings.graph_max_cycles):
        chain = " → ".join(_short(n) for n in cycle) + f" → {_short(cycle[0])}"
        out.append(
            RefactorCandidate(
                id=_candidate_id("cycle", cycle),
                kind="cycle",
                severity="high",
                title=f"Circular dependency among {len(cycle)} files",
                summary=f"These files import each other in a cycle: {chain}. "
                "Break it by extracting the shared piece or inverting a dependency.",
                files=list(cycle),
            )
        )
    return out


def _hub_candidates(data: graph_store.GraphData, settings: Settings) -> list[RefactorCandidate]:
    graph = analysis.build_digraph(data)
    threshold = settings.refactor_hub_degree
    out: list[RefactorCandidate] = []
    for node in graph.nodes():
        fan_in = graph.in_degree(node)
        fan_out = graph.out_degree(node)
        if fan_in >= threshold and fan_out >= threshold:
            out.append(
                RefactorCandidate(
                    id=_candidate_id("hub", [node]),
                    kind="hub",
                    severity="medium",
                    title=f"Coupling hub: {_short(node)}",
                    summary=f"{node} is depended on by {fan_in} files and imports {fan_out} — "
                    "a central, tightly-coupled module. Consider splitting it by responsibility.",
                    files=[node],
                )
            )
    # Most-coupled first.
    out.sort(key=lambda c: c.summary, reverse=True)
    return out


def _violation_candidates(repo_path: str | None, data: graph_store.GraphData) -> list[RefactorCandidate]:
    if repo_path is None or not Path(repo_path).is_dir():
        return []
    try:
        config = rules.load_rules(Path(repo_path))
    except ValueError:
        return []
    if config is None:
        return []

    out: list[RefactorCandidate] = []
    for v in rules.evaluate(config, data):
        out.append(
            RefactorCandidate(
                id=_candidate_id("violation", [v.src_file, v.dst_file]),
                kind="violation",
                severity="high" if v.severity == "error" else "low",
                title=f"Architecture violation: {v.rule}",
                summary=f"{_short(v.src_file)} ({v.from_layer}) depends on "
                f"{_short(v.dst_file)} ({v.to_layer}), which the rule forbids.",
                files=[v.src_file, v.dst_file],
            )
        )
    return out


def detect_candidates(
    conn: sqlite3.Connection, repo: str | None, settings: Settings
) -> list[RefactorCandidate]:
    """Detect refactoring candidates for a repo (default: the first indexed one)."""
    name = repo
    if name is None:
        names = graph_store.list_repos(conn)
        if not names:
            return []
        name = names[0]

    data = graph_store.load_static_graph(conn, name)
    repo_path = graph_store.get_repo_path(conn, name)

    candidates = (
        _cycle_candidates(data, settings)
        + _hub_candidates(data, settings)
        + _violation_candidates(repo_path, data)
    )
    return candidates[: settings.refactor_max_candidates]
