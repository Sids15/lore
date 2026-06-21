"""Graph API: query the static dependency graph (viz, cycles, stats, paths)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite_store
from app.graph import analysis, graph_store, rules
from app.graph.graph_store import GraphData
from app.graph.rules import Violation

router = APIRouter(tags=["graph"])


class GraphNode(BaseModel):
    id: str
    label: str
    file_path: str
    in_degree: int
    out_degree: int
    in_cycle: bool


class GraphLink(BaseModel):
    source: str
    target: str


class GraphViz(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    truncated: bool


class CyclesResponse(BaseModel):
    cycles: list[list[str]]


class PathResponse(BaseModel):
    path: list[str] | None


class ViolationsResponse(BaseModel):
    configured: bool  # whether the repo has a .lore/arch-rules.yml
    violations: list[Violation]


def _load(repo: str | None) -> GraphData:
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        return graph_store.load_static_graph(conn, repo)
    finally:
        conn.close()


@router.get("/graph", response_model=GraphViz)
def graph(repo: str | None = None) -> GraphViz:
    """Return the dependency graph as a visualization payload."""
    settings = get_settings()
    data = _load(repo)
    return GraphViz(**analysis.to_viz(data, settings.graph_max_nodes, settings.graph_max_cycles))


@router.get("/graph/cycles", response_model=CyclesResponse)
def cycles(repo: str | None = None) -> CyclesResponse:
    """Return detected import cycles (circular dependencies)."""
    settings = get_settings()
    data = _load(repo)
    return CyclesResponse(cycles=analysis.find_cycles(data, settings.graph_max_cycles))


@router.get("/graph/stats")
def stats(repo: str | None = None) -> dict:
    """Return node/edge counts and the most-depended-on / most-importing files."""
    return analysis.degree_stats(_load(repo))


@router.get("/graph/path", response_model=PathResponse)
def path(source: str, target: str, repo: str | None = None) -> PathResponse:
    """Return the shortest dependency path from source to target, if any."""
    data = _load(repo)
    if source not in data.nodes or target not in data.nodes:
        raise HTTPException(status_code=404, detail="source or target not in graph")
    return PathResponse(path=analysis.shortest_path(data, source, target))


@router.get("/graph/violations", response_model=ViolationsResponse)
def violations(repo: str | None = None) -> ViolationsResponse:
    """Evaluate the repo's architecture rules against its dependency graph.

    Rules live in `.lore/arch-rules.yml` in the indexed repo and are read fresh on
    each call, so edits take effect on Refresh without re-indexing.
    """
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        # Resolve which repo to evaluate (default: the only/first indexed one).
        name = repo
        if name is None:
            names = graph_store.list_repos(conn)
            if not names:
                return ViolationsResponse(configured=False, violations=[])
            name = names[0]
        repo_path = graph_store.get_repo_path(conn, name)
        data = graph_store.load_static_graph(conn, name)
    finally:
        conn.close()

    if repo_path is None or not Path(repo_path).is_dir():
        return ViolationsResponse(configured=False, violations=[])

    try:
        config = rules.load_rules(Path(repo_path))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if config is None:
        return ViolationsResponse(configured=False, violations=[])
    return ViolationsResponse(configured=True, violations=rules.evaluate(config, data))
