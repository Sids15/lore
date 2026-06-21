"""Architecture graph (Index A, Layer A — static & exact).

Builds a directed dependency graph of how a repository's modules import one
another, derived deterministically from the AST (no LLM). Persisted in SQLite
(`graph_nodes`/`graph_edges`, `layer='static'`) and analyzed with networkx.
"""
