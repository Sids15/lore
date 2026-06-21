"""Tests for the architecture-violation engine."""

from __future__ import annotations

from app.graph import rules
from app.graph.graph_store import GraphData
from app.graph.rules import RuleConfig


def _config() -> RuleConfig:
    return RuleConfig.model_validate(
        {
            "layers": {
                "frontend": ["src/**"],
                "api": ["sidecar/app/api/**"],
                "storage": ["sidecar/app/db/**"],
            },
            "rules": [
                {
                    "name": "API must not depend on the frontend",
                    "from": "api",
                    "to": "frontend",
                    "severity": "error",
                }
            ],
        }
    )


def test_violation_detected():
    graph = GraphData(
        nodes=["sidecar/app/api/graph.py", "src/App.tsx"],
        edges=[("sidecar/app/api/graph.py", "src/App.tsx")],
    )
    found = rules.evaluate(_config(), graph)
    assert len(found) == 1
    v = found[0]
    assert v.rule == "API must not depend on the frontend"
    assert v.severity == "error"
    assert (v.src_file, v.dst_file) == ("sidecar/app/api/graph.py", "src/App.tsx")


def test_allowed_edge_is_not_a_violation():
    # frontend -> api is not forbidden by the (api -> frontend) rule.
    graph = GraphData(
        nodes=["src/App.tsx", "sidecar/app/api/graph.py"],
        edges=[("src/App.tsx", "sidecar/app/api/graph.py")],
    )
    assert rules.evaluate(_config(), graph) == []


def test_unmatched_files_yield_no_violation():
    graph = GraphData(
        nodes=["sidecar/app/db/x.py", "sidecar/app/db/y.py"],
        edges=[("sidecar/app/db/x.py", "sidecar/app/db/y.py")],
    )
    assert rules.evaluate(_config(), graph) == []


def test_glob_double_star_matches_nested():
    config = RuleConfig.model_validate(
        {
            "layers": {"a": ["pkg/**"], "b": ["other/**"]},
            "rules": [{"name": "r", "from": "a", "to": "b"}],
        }
    )
    graph = GraphData(
        nodes=["pkg/deep/nested/mod.py", "other/x.py"],
        edges=[("pkg/deep/nested/mod.py", "other/x.py")],
    )
    found = rules.evaluate(config, graph)
    assert len(found) == 1
    assert found[0].severity == "warning"  # default severity


def test_default_severity_is_warning():
    rule = rules.Rule.model_validate({"name": "r", "from": "a", "to": "b"})
    assert rule.severity == "warning"


def test_load_rules_missing_file(tmp_path):
    assert rules.load_rules(tmp_path) is None


def test_load_rules_parses_file(tmp_path):
    (tmp_path / ".lore").mkdir()
    (tmp_path / ".lore" / "arch-rules.yml").write_text(
        "layers:\n  a: ['x/**']\nrules:\n  - name: r\n    from: a\n    to: a\n",
        encoding="utf-8",
    )
    config = rules.load_rules(tmp_path)
    assert config is not None
    assert "a" in config.layers
    assert config.rules[0].from_layer == "a"


def test_load_rules_invalid_yaml_raises(tmp_path):
    (tmp_path / ".lore").mkdir()
    (tmp_path / ".lore" / "arch-rules.yml").write_text("layers: [unclosed\n", encoding="utf-8")
    try:
        rules.load_rules(tmp_path)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
