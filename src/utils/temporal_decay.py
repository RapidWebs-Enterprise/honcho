"""Temporal decay utilities for KG retrieval.

Applies exponential decay weighting to conclusions based on age,
making recent information more relevant in semantic search results.
"""

import math
from datetime import datetime
from typing import Any


def calculate_decay(age_days: float, half_life: float = 7.0) -> float:
    """Calculate temporal decay weight.

    Uses exponential decay: weight = exp(-age_days * ln(2) / half_life)

    Args:
        age_days: Age of conclusion in days
        half_life: Days for weight to reduce by 50% (default: 7)

    Returns:
        Weight between 0.0 and 1.0
    """
    if half_life <= 0:
        return 1.0
    return math.exp(-age_days * math.log(2) / half_life)


def apply_decay(
    conclusions: list[dict[str, Any]],
    half_life: float = 7.0,
    min_weight: float = 0.01,
    max_age_days: float = 365.0,
) -> list[dict[str, Any]]:
    """Apply temporal decay to list of conclusions.

    Adds _decay_weight to each conclusion and re-sorts by combined score.

    Args:
        conclusions: List of conclusion dicts with 'created_at' and 'score'
        half_life: Days for 50% weight reduction
        min_weight: Minimum weight floor
        max_age_days: Conclusions older than this get min_weight

    Returns:
        Sorted list of conclusions with _decay_weight added
    """
    now = datetime.now(datetime.UTC)

    for c in conclusions:
        created = c.get("created_at")
        if created:
            # Parse ISO format timestamp
            if isinstance(created, str):
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    created_dt = now
            else:
                created_dt = created

            age_seconds = (now - created_dt).total_seconds()
            age_days = age_seconds / 86400

            if age_days > max_age_days:
                c["_decay_weight"] = min_weight
            else:
                c["_decay_weight"] = max(min_weight, calculate_decay(age_days, half_life))
        else:
            # No timestamp = assume recent
            c["_decay_weight"] = 1.0

    # Sort by combined score (semantic * decay)
    return sorted(
        conclusions,
        key=lambda x: x.get("score", 0) * x.get("_decay_weight", 1),
        reverse=True,
    )


def get_decay_config() -> dict[str, Any]:
    """Get temporal decay configuration from Honcho settings.

    Returns:
        Config dict with half_life_days, min_weight, max_age_days
    """
    from src.config import settings

    decay_config = getattr(settings, "temporal_decay", {})
    return {
        "half_life_days": decay_config.get("half_life_days", 7),
        "min_weight": decay_config.get("min_weight", 0.01),
        "max_age_days": decay_config.get("max_age_days", 365),
        "enabled": decay_config.get("enabled", True),
    }
