"""Maximal Marginal Relevance (MMR) re-selection for retrieval diversity.

The cross-encoder reranker scores each candidate against the query independently,
so it can return several near-duplicate chunks (the same function in slightly
different windows, or two paraphrases of one fact). Those crowd distinct evidence
out of the small answer context. MMR re-selects the final top-k to balance
relevance against novelty: each pick maximises its relevance minus its similarity
to what's already chosen.

Pure-Python (no numpy) and fails open — if any candidate vector is missing it
returns the relevance order unchanged, mirroring the reranker's fallback.
"""

from __future__ import annotations

import math


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is zero)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def select(
    order: list[int],
    vectors: list,
    *,
    k: int,
    lambda_: float = 0.7,
) -> list[int]:
    """Re-select up to ``k`` indices from ``order`` to balance relevance + novelty.

    ``order`` is candidate indices already sorted best-first (the rerank output);
    ``vectors[i]`` is the embedding for candidate index ``i``. ``lambda_`` weights
    relevance against diversity (1.0 = pure relevance, 0.0 = pure diversity).
    Returns indices in selection order, falling back to ``order[:k]`` when k is
    non-positive or any candidate vector is unusable.
    """
    n = len(order)
    if n == 0 or k <= 0:
        return order[: max(k, 0)]
    k = min(k, n)

    # Materialise the vectors we need as plain float lists. Any missing/empty/
    # non-numeric vector means we can't measure diversity -> fall back to order.
    try:
        vecs = {i: [float(x) for x in vectors[i]] for i in order}
    except (TypeError, IndexError, ValueError):
        return order[:k]
    if any(not vecs[i] for i in order):
        return order[:k]

    # Rank-based relevance in (0, 1], higher is better. Using rank (not raw
    # scores) keeps this uniform whether ``order`` came from the cross-encoder or
    # the RRF fallback.
    rel = {idx: (n - pos) / n for pos, idx in enumerate(order)}

    selected = [order[0]]
    remaining = order[1:]
    while len(selected) < k and remaining:
        best: int | None = None
        best_score = -math.inf
        for candidate in remaining:
            max_sim = max(_cosine(vecs[candidate], vecs[s]) for s in selected)
            score = lambda_ * rel[candidate] - (1.0 - lambda_) * max_sim
            if score > best_score:
                best, best_score = candidate, score
        assert best is not None  # remaining is non-empty in the loop
        selected.append(best)
        remaining.remove(best)
    return selected
