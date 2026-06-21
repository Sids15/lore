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


_VALID_LAYERS = {"static", "semantic"}


def _check_layer(layer: str) -> str:
    if layer not in _VALID_LAYERS:
        raise HTTPException(status_code=400, detail="layer must be 'static' or 'semantic'")
    return layer


def _load(repo: str | None, layer: str = "static") -> GraphData:
    settings = get_settings()
    conn = sqlite_store.connect(settings.data_path)
    try:
        return graph_store.load_graph(conn, repo, layer)
    finally:
        conn.close()


@router.get("/graph", response_model=GraphViz)
def graph(repo: str | None = None, layer: str = "static") -> GraphViz:
    """Return a graph layer (static imports or semantic relationships) for viz."""
    settings = get_settings()
    data = _load(repo, _check_layer(layer))
    return GraphViz(**analysis.to_viz(data, settings.graph_max_nodes, settings.graph_max_cycles))


@router.get("/graph/cycles", response_model=CyclesResponse)
def cycles(repo: str | None = None, layer: str = "static") -> CyclesResponse:
    """Return cycles in the given graph layer (circular dependencies/calls)."""
    settings = get_settings()
    data = _load(repo, _check_layer(layer))
    return CyclesResponse(cycles=analysis.find_cycles(data, settings.graph_max_cycles))


@router.get("/graph/stats")
def stats(repo: str | None = None, layer: str = "static") -> dict:
    """Return node/edge counts and degree rankings for the given layer."""
    return analysis.degree_stats(_load(repo, _check_layer(layer)))


@router.get("/graph/path", response_model=PathResponse)
def path(
    source: str, target: str, repo: str | None = None, layer: str = "static"
) -> PathResponse:
    """Return the shortest path from source to target in the given layer, if any."""
    data = _load(repo, _check_layer(layer))
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
