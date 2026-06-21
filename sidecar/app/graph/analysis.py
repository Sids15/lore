"""Graph analysis over the static dependency graph (networkx).

Pure functions operating on a loaded :class:`GraphData`, so they are easy to test
without a database: cycle detection, degree ranking, shortest path, and a
visualization payload that flags nodes participating in import cycles.
"""

from __future__ import annotations

import networkx as nx

from app.graph.graph_store import GraphData


def build_digraph(data: GraphData) -> nx.DiGraph:
    """Build a directed graph from loaded nodes and edges."""
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(data.nodes)
    graph.add_edges_from(data.edges)
    return graph


def find_cycles(data: GraphData, max_cycles: int) -> list[list[str]]:
    """Return up to ``max_cycles`` import cycles (each a list of file paths)."""
    graph = build_digraph(data)
    cycles: list[list[str]] = []
    for cycle in nx.simple_cycles(graph):
        cycles.append(cycle)
        if len(cycles) >= max_cycles:
            break
    return cycles


def _cycle_nodes(graph: nx.DiGraph, max_cycles: int) -> set[str]:
    nodes: set[str] = set()
    for index, cycle in enumerate(nx.simple_cycles(graph)):
        nodes.update(cycle)
        if index + 1 >= max_cycles:
            break
    return nodes


def degree_stats(data: GraphData, top: int = 10) -> dict:
    """Rank the most depended-on (in-degree) and most-importing (out-degree) files."""
    graph = build_digraph(data)
    in_deg = sorted(graph.in_degree(), key=lambda kv: kv[1], reverse=True)
    out_deg = sorted(graph.out_degree(), key=lambda kv: kv[1], reverse=True)
    return {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "most_depended_on": [
            {"file": n, "in_degree": d} for n, d in in_deg[:top] if d > 0
        ],
        "most_dependencies": [
            {"file": n, "out_degree": d} for n, d in out_deg[:top] if d > 0
        ],
    }


def shortest_path(data: GraphData, source: str, target: str) -> list[str] | None:
    """Return the shortest dependency path source -> target, or None."""
    graph = build_digraph(data)
    if source not in graph or target not in graph:
        return None
    try:
        return nx.shortest_path(graph, source, target)
    except nx.NetworkXNoPath:
        return None


def to_viz(data: GraphData, max_nodes: int, max_cycles: int) -> dict:
    """Build a visualization payload (nodes + links), capped at ``max_nodes``.

    When the graph is larger than the cap, the highest-degree nodes are kept so
    the most architecturally significant structure is shown.
    """
    graph = build_digraph(data)
    cycle_nodes = _cycle_nodes(graph, max_cycles)

    all_nodes = list(graph.nodes())
    if len(all_nodes) > max_nodes:
        all_nodes.sort(key=lambda n: graph.in_degree(n) + graph.out_degree(n), reverse=True)
        keep = set(all_nodes[:max_nodes])
    else:
        keep = set(all_nodes)

    nodes = [
        {
            "id": n,
            "label": n.rsplit("/", 1)[-1],
            "file_path": n,
            "in_degree": graph.in_degree(n),
            "out_degree": graph.out_degree(n),
            "in_cycle": n in cycle_nodes,
        }
        for n in keep
    ]
    links = [
        {"source": s, "target": t}
        for s, t in graph.edges()
        if s in keep and t in keep
    ]
    return {"nodes": nodes, "links": links, "truncated": len(keep) < graph.number_of_nodes()}
