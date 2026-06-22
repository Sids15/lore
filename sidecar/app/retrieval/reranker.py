"""Cross-encoder reranker (ONNX, via fastembed).

Hybrid search merges two ranked lists with RRF, which is fast but only sees each
result list's positions. A cross-encoder reads the query and each candidate
*together*, giving a much sharper relevance signal. We run a small cross-encoder
as an ONNX model through fastembed (no PyTorch).

The model is loaded lazily on first use. If reranking is disabled, the model
can't be loaded, or inference fails (e.g. out of memory), retrieval falls back to
the original (RRF) order — and the offending model is remembered so it isn't
retried on every query.
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
# Models that failed to load (e.g. out of memory) — don't retry them every query.
_failed_models: set[str] = set()


def _mark_failed(model_name: str) -> None:
    """Remember a model that can't be used, and drop any cached instance."""
    global _encoder, _encoder_model
    _failed_models.add(model_name)
    _encoder = None
    _encoder_model = None


def _go_offline_if_cached(model_name: str, cache_dir: Path) -> None:
    """If the model is already on disk, force HuggingFace into offline mode.

    Local-first: once the weights are cached we never want network calls — not
    even the cache-revalidation pings huggingface_hub makes on each load. The
    genuine first-ever download (when nothing is cached) still uses the network.
    """
    folder = "models--" + model_name.replace("/", "--")
    if (cache_dir / folder / "snapshots").is_dir():
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _get_encoder(model_name: str, cache_dir: Path):
    """Return a cached cross-encoder, or None if it cannot be loaded."""
    global _encoder, _encoder_model
    if _encoder is not None and _encoder_model == model_name:
        return _encoder
    if model_name in _failed_models:
        return None  # already known-bad this session; stay on RRF without re-trying
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache_dir.mkdir(parents=True, exist_ok=True)
        _go_offline_if_cached(model_name, cache_dir)
        _encoder = TextCrossEncoder(model_name, cache_dir=str(cache_dir), lazy_load=True)
        _encoder_model = model_name
    except Exception as error:  # noqa: BLE001 - any failure -> fall back to RRF
        logger.warning("Reranker '%s' unavailable (%s); using RRF order", model_name, error)
        _mark_failed(model_name)
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
                # Inference failed (e.g. out of memory). Don't retry this model.
                logger.warning(
                    "Reranking with '%s' failed (%s); using RRF order",
                    settings.rerank_model, error,
                )
                _mark_failed(settings.rerank_model)

    return order if top_k is None else order[:top_k]
