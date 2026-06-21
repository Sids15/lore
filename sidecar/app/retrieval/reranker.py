"""Cross-encoder reranker (ONNX, via fastembed).

Hybrid search merges two ranked lists with RRF, which is fast but only sees each
result list's positions. A cross-encoder reads the query and each candidate
*together*, giving a much sharper relevance signal. We run ``bge-reranker-base``
as an ONNX model through fastembed (no PyTorch).

The model is loaded lazily on first use. If reranking is disabled or the model
fails to load, retrieval falls back to the original (RRF) order, so answering
never breaks because of the reranker.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)

# The model is a public, one-time download from the HuggingFace Hub; it then runs
# fully offline. Silence the (harmless) symlink warning on Windows.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Cached encoder instance, keyed by model name. fastembed is imported lazily so a
# missing/optional install doesn't break import of the rest of the app.
_encoder = None
_encoder_model: str | None = None


def _get_encoder(model_name: str, cache_dir: Path):
    """Return a cached cross-encoder, or None if it cannot be loaded."""
    global _encoder, _encoder_model
    if _encoder is not None and _encoder_model == model_name:
        return _encoder
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache_dir.mkdir(parents=True, exist_ok=True)
        _encoder = TextCrossEncoder(model_name, cache_dir=str(cache_dir), lazy_load=True)
        _encoder_model = model_name
    except Exception as error:  # noqa: BLE001 - any failure -> fall back to RRF
        logger.warning("Reranker unavailable (%s); falling back to RRF order", error)
        _encoder = None
        _encoder_model = None
    return _encoder


def rerank(
    query: str,
    documents: list[str],
    settings: Settings,
    *,
    top_k: int | None = None,
) -> list[int]:
    """Return document indices ordered best-first.

    ``documents[i]`` is the text for candidate ``i``; the returned list contains
    those indices reordered by relevance (truncated to ``top_k`` if given). When
    reranking is disabled or unavailable, the original order is preserved.
    """
    order = list(range(len(documents)))
    if not documents:
        return order

    if settings.rerank_enabled:
        encoder = _get_encoder(settings.rerank_model, settings.model_cache_path)
        if encoder is not None:
            try:
                scores = list(encoder.rerank(query, documents))
                order = sorted(order, key=lambda i: scores[i], reverse=True)
            except Exception as error:  # noqa: BLE001 - keep RRF order on failure
                logger.warning("Reranking failed (%s); using RRF order", error)

    return order if top_k is None else order[:top_k]
