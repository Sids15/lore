"""Architecture-violation engine.

A repository may declare layered architecture rules in `.lore/arch-rules.yml`.
Each rule forbids dependencies from one layer to another; we evaluate them against
the static dependency graph and report every import edge that breaks a rule.

Example `.lore/arch-rules.yml`::

    layers:
      frontend: ["src/**"]
      api:      ["sidecar/app/api/**"]
      storage:  ["sidecar/app/db/**", "sidecar/app/index/**"]
    rules:
      - name: "API must not depend on the frontend"
        from: api
        to: frontend
        severity: error
"""

from __future__ import annotations

from pathlib import Path

import pathspec
import yaml
from pydantic import BaseModel, Field

from app.graph.graph_store import GraphData

RULES_RELATIVE_PATH = ".lore/arch-rules.yml"


class Rule(BaseModel):
    """A forbidden dependency from one layer to another."""

    name: str
    from_layer: str = Field(alias="from")
    to_layer: str = Field(alias="to")
    severity: str = "warning"  # "error" | "warning"

    model_config = {"populate_by_name": True}


class RuleConfig(BaseModel):
    """Parsed `.lore/arch-rules.yml`."""

    layers: dict[str, list[str]] = {}
    rules: list[Rule] = []


class Violation(BaseModel):
    """A single dependency edge that breaks a rule."""

    rule: str
    severity: str
    src_file: str
    dst_file: str
    from_layer: str
    to_layer: str


def rules_path(repo_root: Path) -> Path:
    return repo_root / RULES_RELATIVE_PATH


def load_rules(repo_root: Path) -> RuleConfig | None:
    """Load and validate the repo's architecture rules, or None if absent.

    Raises ``ValueError`` on malformed YAML/schema so callers can surface a clear
    error.
    """
    path = rules_path(repo_root)
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return RuleConfig.model_validate(raw)
    except (yaml.YAMLError, ValueError) as error:
        raise ValueError(f"Invalid {RULES_RELATIVE_PATH}: {error}") from error


def _layer_specs(config: RuleConfig) -> dict[str, pathspec.PathSpec]:
    """Compile each layer's globs into a matcher (gitignore-style)."""
    return {
        name: pathspec.PathSpec.from_lines("gitignore", patterns)
        for name, patterns in config.layers.items()
    }


def _layers_for(file_path: str, specs: dict[str, pathspec.PathSpec]) -> set[str]:
    return {name for name, spec in specs.items() if spec.match_file(file_path)}


def evaluate(config: RuleConfig, graph: GraphData) -> list[Violation]:
    """Return every dependency edge that violates a rule."""
    specs = _layer_specs(config)
    # Cache the layer membership of each file once.
    membership = {
        file_path: _layers_for(file_path, specs) for file_path in graph.nodes
    }

    violations: list[Violation] = []
    for src, dst in graph.edges:
        src_layers = membership.get(src) or _layers_for(src, specs)
        dst_layers = membership.get(dst) or _layers_for(dst, specs)
        for rule in config.rules:
            if rule.from_layer in src_layers and rule.to_layer in dst_layers:
                violations.append(
                    Violation(
                        rule=rule.name,
                        severity=rule.severity,
                        src_file=src,
                        dst_file=dst,
                        from_layer=rule.from_layer,
                        to_layer=rule.to_layer,
                    )
                )
    return violations
