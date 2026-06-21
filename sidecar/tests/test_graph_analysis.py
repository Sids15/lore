"""Tests for graph analysis (cycles, degrees, paths, viz)."""

from __future__ import annotations

from app.graph import analysis
from app.graph.graph_store import GraphData


def _data() -> GraphData:
    # a -> b -> c -> a  (a cycle), plus d -> b (extra in-edge to b)
    return GraphData(
        nodes=["a", "b", "c", "d"],
        edges=[("a", "b"), ("b", "c"), ("c", "a"), ("d", "b")],
    )


def test_find_cycles_detects_cycle():
    cycles = analysis.find_cycles(_data(), max_cycles=10)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_find_cycles_respects_cap():
    # Two independent 2-cycles; cap at 1 returns only one.
    data = GraphData(nodes=["a", "b", "x", "y"], edges=[("a", "b"), ("b", "a"), ("x", "y"), ("y", "x")])
    assert len(analysis.find_cycles(data, max_cycles=1)) == 1


def test_degree_stats_ranks_most_depended_on():
    stats = analysis.degree_stats(_data())
    assert stats["node_count"] == 4
    assert stats["edge_count"] == 4
    # b has in-degree 2 (from a and d) — the most depended-on.
    assert stats["most_depended_on"][0] == {"file": "b", "in_degree": 2}


def test_shortest_path():
    assert analysis.shortest_path(_data(), "d", "c") == ["d", "b", "c"]
    assert analysis.shortest_path(_data(), "c", "d") is None  # no path
    assert analysis.shortest_path(_data(), "missing", "c") is None


def test_to_viz_flags_cycle_nodes():
    viz = analysis.to_viz(_data(), max_nodes=100, max_cycles=10)
    by_id = {n["id"]: n for n in viz["nodes"]}
    assert by_id["a"]["in_cycle"] is True
    assert by_id["d"]["in_cycle"] is False
    assert viz["truncated"] is False
    assert len(viz["links"]) == 4


def test_to_viz_caps_nodes():
    data = GraphData(nodes=[str(i) for i in range(10)], edges=[("0", "1"), ("0", "2")])
    viz = analysis.to_viz(data, max_nodes=3, max_cycles=10)
    assert len(viz["nodes"]) == 3
    assert viz["truncated"] is True
    # The high-degree hub "0" must be retained.
    assert any(n["id"] == "0" for n in viz["nodes"])
