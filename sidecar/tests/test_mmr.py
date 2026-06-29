"""Tests for MMR diversity re-selection (pure, no network)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.retrieval import mmr


def test_mmr_lambda_must_be_within_unit_interval():
    # Out-of-range lambda would invert MMR into an anti-diversity ranker; reject it.
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            Settings(mmr_lambda=bad)
    # Bounds are inclusive.
    assert Settings(mmr_lambda=0.0).mmr_lambda == 0.0
    assert Settings(mmr_lambda=1.0).mmr_lambda == 1.0


def test_lambda_one_is_pure_relevance():
    # With lambda=1.0 the diversity term vanishes, so the relevance order wins
    # regardless of how similar the vectors are.
    order = [0, 1, 2, 3]
    vectors = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
    assert mmr.select(order, vectors, k=3, lambda_=1.0) == [0, 1, 2]


def test_diversity_demotes_near_duplicate():
    # Indices 0 and 1 are identical; 2 is orthogonal. Balanced lambda should pick
    # 0 (top relevance) then 2 (novel), demoting the near-duplicate 1.
    order = [0, 1, 2]
    vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    assert mmr.select(order, vectors, k=2, lambda_=0.5) == [0, 2]


def test_k_larger_than_n_returns_all():
    order = [0, 1]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    assert mmr.select(order, vectors, k=5, lambda_=0.7) == [0, 1]


def test_empty_order_returns_empty():
    assert mmr.select([], [], k=3, lambda_=0.7) == []


def test_non_positive_k_returns_empty():
    assert mmr.select([0, 1], [[1.0], [1.0]], k=0, lambda_=0.7) == []


def test_missing_vector_falls_back_to_order():
    # A None vector means diversity can't be measured -> fall back to order[:k].
    order = [0, 1, 2]
    vectors = [[1.0, 0.0], None, [0.0, 1.0]]
    assert mmr.select(order, vectors, k=2, lambda_=0.5) == [0, 1]


def test_zero_vector_similarity_is_safe():
    # A zero vector has 0 cosine with everything; selection still completes.
    order = [0, 1]
    vectors = [[0.0, 0.0], [1.0, 0.0]]
    assert mmr.select(order, vectors, k=2, lambda_=0.5) == [0, 1]
