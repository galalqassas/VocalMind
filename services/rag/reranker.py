"""
Cross-encoder reranking for VocalMind RAG retrieval.

Dense vector search (Qdrant + snowflake-arctic-embed2) is recall-oriented:
it casts a wide net but ranks imperfectly. A cross-encoder reads the
(query, chunk) pair jointly and produces a far sharper relevance score,
which is what lifts RAGAS context-precision and faithfulness.

Flow: retrieve a wide candidate pool (RERANK_CANDIDATE_K) from Qdrant,
rerank here, keep the top `top_k`. The model is loaded lazily once and
cached. If the reranker cannot be loaded (offline, missing deps), we log
and fall back to the original dense ordering so retrieval never breaks.
"""

from __future__ import annotations

import logging
from threading import Lock

from qdrant_client.models import ScoredPoint

try:
    from .config import settings
except ImportError:  # pragma: no cover - allows direct script/test imports
    from config import settings

logger = logging.getLogger(__name__)

_model = None
_model_failed = False
_lock = Lock()


def _get_model():
    """Lazily load and cache the cross-encoder. Returns None on failure."""
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    with _lock:
        if _model is not None or _model_failed:
            return _model
        try:
            from sentence_transformers import CrossEncoder

            logger.info("Loading reranker model: %s", settings.RERANK_MODEL)
            _model = CrossEncoder(settings.RERANK_MODEL)
        except Exception as exc:  # pragma: no cover - environment dependent
            _model_failed = True
            logger.warning(
                "Reranker unavailable (%s); falling back to dense ordering.", exc
            )
    return _model


def rerank_points(
    query: str,
    points: list[ScoredPoint],
    top_k: int,
) -> list[ScoredPoint]:
    """
    Reorder Qdrant results by cross-encoder relevance, keep the top_k.

    The original Qdrant cosine ``score`` on each point is preserved; only
    the ordering and truncation change. If reranking is disabled or the
    model is unavailable, the dense-ordered top_k is returned unchanged.
    """
    if not settings.RERANK_ENABLED or len(points) <= 1:
        return points[:top_k]

    model = _get_model()
    if model is None:
        return points[:top_k]

    pairs = [(query, (pt.payload or {}).get("text", "")) for pt in points]
    try:
        scores = model.predict(pairs)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Reranker prediction failed (%s); using dense order.", exc)
        return points[:top_k]

    ranked = sorted(
        zip(points, scores, strict=True),
        key=lambda ps: float(ps[1]),
        reverse=True,
    )

    # Drop chunks below the minimum relevance threshold.
    # bge-reranker-v2-m3 scores: roughly -10 (irrelevant) to +10 (highly relevant).
    # Filtering below RERANK_MIN_SCORE removes clearly off-topic chunks that would
    # drag down RAGAS context precision. Always keep at least 1 chunk.
    threshold = settings.RERANK_MIN_SCORE
    above = [pt for pt, s in ranked if float(s) >= threshold]
    candidates = above if above else [ranked[0][0]]
    return candidates[:top_k]
