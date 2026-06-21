"""Retrieval: turn a question into the most relevant code chunks.

Hybrid search (vector + full-text, merged with Reciprocal Rank Fusion) produces
candidates, then an ONNX cross-encoder reranker re-scores them for final ordering.
"""
