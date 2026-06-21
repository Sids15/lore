"""Graph API: query the static dependency graph (viz, cycles, stats, paths)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import sqlite_store
from app.graph import analysis, graph_store
from app.graph.graph_store import GraphData

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
