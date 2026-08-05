"""
Scoring utilities for hybrid retrieval.

Provides:
- **BM25 normalization**: Sigmoid normalization of raw BM25 scores to [0, 1].
- **BM25 parameter selection**: Query-length-adaptive sigmoid parameters.
- **Additive scoring**: Combined scoring with semantic + BM25 + entity boost.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional



def get_bm25_params(query: str, *, lemmatized: Optional[str] = None) -> tuple:
    """Get BM25 sigmoid parameters based on query length.

    Longer queries tend to have higher raw BM25 scores, so we adjust
    the sigmoid midpoint and steepness accordingly.

    Returns:
        (midpoint, steepness) for sigmoid normalization.
    """
    if lemmatized is None:
        from mem0.utils.lemmatization import lemmatize_for_bm25

        lemmatized = lemmatize_for_bm25(query)
    num_terms = len(lemmatized.split()) if lemmatized else 1

    if num_terms <= 3:
        return 5.0, 0.7
    elif num_terms <= 6:
        return 7.0, 0.6
    elif num_terms <= 9:
        return 9.0, 0.5
    elif num_terms <= 15:
        return 10.0, 0.5
    else:
        return 12.0, 0.5


def normalize_bm25(raw_score: float, midpoint: float, steepness: float) -> float:
    """Normalize BM25 score to [0, 1] using logistic sigmoid.

    Args:
        raw_score: Raw BM25 score (unbounded, typically 0-20+).
        midpoint: Score at which sigmoid outputs 0.5.
        steepness: Controls how quickly sigmoid transitions.

    Returns:
        Normalized score in range [0, 1].
    """
    return 1.0 / (1.0 + math.exp(-steepness * (raw_score - midpoint)))


ENTITY_BOOST_WEIGHT = 0.5
IMPORTANCE_BOOST_WEIGHT = 0.3
RECENCY_BOOST_WEIGHT = 0.2
DEFAULT_RECENCY_HALF_LIFE_DAYS = 30.0


def compute_recency_score(
    timestamp_val: Optional[Any],
    half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Calculate exponential recency decay score in [0.0, 1.0].

    Formula: score = exp(-days_old / half_life_days)
    """
    if not timestamp_val or half_life_days <= 0:
        return 0.0

    try:
        if isinstance(timestamp_val, (int, float)):
            dt = datetime.fromtimestamp(timestamp_val, tz=timezone.utc)
        elif isinstance(timestamp_val, str):
            dt = datetime.fromisoformat(timestamp_val.replace("Z", "+00:00"))
        elif isinstance(timestamp_val, datetime):
            dt = timestamp_val if timestamp_val.tzinfo else timestamp_val.replace(tzinfo=timezone.utc)
        else:
            return 0.0

        now = datetime.now(timezone.utc)
        days_old = max(0.0, (now - dt).total_seconds() / 86400.0)
        return math.exp(-days_old / half_life_days)
    except Exception:
        return 0.0


def score_and_rank(
    semantic_results: List[Dict[str, Any]],
    bm25_scores: Dict[str, float],
    entity_boosts: Dict[str, float],
    threshold: float,
    top_k: int,
    explain: bool = False,
    use_recency_decay: bool = True,
    half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> List[Dict[str, Any]]:
    """Score candidates additively and return top-k results.

    Supports vector similarity + BM25 keyword rank + entity boost +
    importance weighting + exponential recency time decay.

    Threshold gates the semantic score BEFORE combining -- candidates
    below the threshold are excluded even if BM25/entity/importance would boost them.

    Args:
        semantic_results: Candidate memories from vector search.
        bm25_scores: Normalized keyword scores keyed by memory ID.
        entity_boosts: Entity-link boosts keyed by memory ID.
        threshold: Minimum semantic score required before hybrid scoring.
        top_k: Maximum number of results to return.
        explain: Include score_details in each result when true.
        use_recency_decay: Include exponential recency time decay scoring.
        half_life_days: Half-life in days for recency decay calculation.

    Returns:
        List of scored result dicts sorted by combined score descending.
    """
    has_bm25 = bool(bm25_scores)
    has_entity = bool(entity_boosts)

    scored: List[Dict[str, Any]] = []

    for result in semantic_results:
        mem_id = result.get("id")
        if mem_id is None:
            continue

        semantic_score = result.get("score") or 0.0
        if semantic_score < threshold:
            continue

        mem_id_str = str(mem_id)
        bm25_score = bm25_scores.get(mem_id_str, 0.0)
        entity_boost = entity_boosts.get(mem_id_str, 0.0)
        payload = result.get("payload") or {}

        # Extract importance rating (1-10 scale mapped to 0.1-1.0)
        raw_importance = payload.get("importance") if isinstance(payload, dict) else None
        importance_score = 0.0
        has_importance = False
        if raw_importance is not None:
            try:
                imp_val = float(raw_importance)
                importance_score = max(0.1, min(imp_val / 10.0, 1.0))
                has_importance = True
            except (ValueError, TypeError):
                pass

        # Compute recency decay score from timestamp fields
        recency_score = 0.0
        has_recency = False
        if use_recency_decay and isinstance(payload, dict):
            ts = payload.get("created_at") or payload.get("updated_at")
            if ts:
                recency_score = compute_recency_score(ts, half_life_days=half_life_days)
                has_recency = recency_score > 0.0

        max_possible = 1.0
        if has_bm25:
            max_possible += 1.0
        if has_entity:
            max_possible += ENTITY_BOOST_WEIGHT
        if has_importance:
            max_possible += IMPORTANCE_BOOST_WEIGHT
        if has_recency:
            max_possible += RECENCY_BOOST_WEIGHT

        raw_combined = (
            semantic_score
            + bm25_score
            + entity_boost
            + (importance_score * IMPORTANCE_BOOST_WEIGHT if has_importance else 0.0)
            + (recency_score * RECENCY_BOOST_WEIGHT if has_recency else 0.0)
        )
        combined = min(raw_combined / max_possible, 1.0)

        scored_result = {
            "id": mem_id_str,
            "score": combined,
            "payload": payload,
        }
        if explain:
            scored_result["score_details"] = {
                "semantic_score": semantic_score,
                "bm25_score": bm25_score,
                "entity_boost": entity_boost,
                "importance_score": importance_score if has_importance else 0.0,
                "recency_score": recency_score if has_recency else 0.0,
                "raw_score": raw_combined,
                "max_possible_score": max_possible,
                "final_score": combined,
                "threshold": threshold,
            }
        scored.append(scored_result)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

