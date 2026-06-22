"""Lightweight, fully-local evaluation harness.

Reports the PRD's quality metrics over a small golden question set
(`.lore/eval.yml`): retrieval recall@k, faithfulness (grounding rate), and answer
relevancy (question/answer embedding similarity) — no RAGAS/langchain dependency.
"""
