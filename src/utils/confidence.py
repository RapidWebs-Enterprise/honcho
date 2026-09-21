"""Confidence scoring for KG conclusions.

Computes multi-signal confidence based on:
- Source credibility (tool_result > conversation > speculation)
- Temporal freshness (exponential decay)
- Consensus (number of independent sources)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default weights
SOURCE_WEIGHT = 0.4
FRESHNESS_WEIGHT = 0.3
CONSENSUS_WEIGHT = 0.3

# Default half-life for temporal decay (days)
DEFAULT_HALF_LIFE_DAYS = 7.0

# Minimum confidence threshold for filtering
DEFAULT_MIN_CONFIDENCE = 0.3

# Source credibility scores
SOURCE_CREDIBILITY: dict[str, float] = {
    "tool_result": 1.0,
    "external_api": 0.9,
    "conversation": 0.7,
    "speculation": 0.3,
    "unknown": 0.5,
}

# Max sources to consider for consensus
MAX_CONSENSUS_SOURCES = 5


def calculate_confidence(
    conclusion: dict[str, Any],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    source_weights: dict[str, float] | None = None,
) -> float:
    """Calculate confidence score for a conclusion.

    Args:
        conclusion: Dictionary with 'sources', 'created_at', 'source_type'
        half_life_days: Days for 50% decay
        source_weights: Custom source credibility weights

    Returns:
        Float between 0.0 and 1.0
    """
    # Source credibility
    weights = source_weights or SOURCE_CREDIBILITY
    source_type = conclusion.get("source_type", "unknown")
    source_score = weights.get(source_type, weights.get("unknown", 0.5))

    # Temporal freshness
    created_at = conclusion.get("created_at")
    if created_at:
        if isinstance(created_at, str):
            created_dt = datetime.fromisoformat(created_at)
        else:
            created_dt = created_at
        # Clamp to now (prevent future timestamps)
        created_dt = min(created_dt, datetime.now(timezone.utc))
        age_days = (datetime.now(timezone.utc) - created_dt).days
        freshness = math.exp(-age_days * math.log(2) / half_life_days)
    else:
        freshness = 0.5  # Unknown age = neutral

    # Consensus (number of unique sources)
    sources = conclusion.get("sources", [])
    # Deduplicate by source ID
    unique_sources = set()
    for s in sources:
        if isinstance(s, dict):
            unique_sources.add(s.get("id", s.get("type", "")))
        else:
            unique_sources.add(str(s))
    consensus = min(1.0, len(unique_sources) / MAX_CONSENSUS_SOURCES)

    # Weighted combination
    confidence = (
        SOURCE_WEIGHT * source_score +
        FRESHNESS_WEIGHT * freshness +
        CONSENSUS_WEIGHT * consensus
    )

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, confidence))


def filter_by_confidence(
    conclusions: list[dict[str, Any]],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter conclusions by minimum confidence and return stats.

    Args:
        conclusions: List of conclusion dictionaries
        min_confidence: Minimum confidence threshold
        half_life_days: Days for temporal decay

    Returns:
        Tuple of (filtered_conclusions, stats)
    """
    scored = []
    for c in conclusions:
        c_copy = c.copy()
        c_copy["confidence"] = calculate_confidence(c, half_life_days)
        scored.append(c_copy)

    # Filter
    filtered = [c for c in scored if c["confidence"] >= min_confidence]

    # Compute stats
    stats = {
        "total_matched": len(conclusions),
        "filtered_by_confidence": len(conclusions) - len(filtered),
        "avg_confidence": (
            sum(c["confidence"] for c in scored) / len(scored)
            if scored else 0.0
        ),
        "min_returned": (
            min(c["confidence"] for c in filtered) if filtered else 0.0
        ),
    }

    return filtered, stats


def enrich_with_provenance(
    conclusions: list[dict[str, Any]],
    max_sources_per_conclusion: int = 5,
) -> list[dict[str, Any]]:
    """Add provenance info to conclusions.

    Args:
        conclusions: List of conclusion dictionaries
        max_sources_per_conclusion: Max sources to include

    Returns:
        List of conclusions with provenance added
    """
    enriched = []
    for c in conclusions:
        c_copy = c.copy()
        sources = c.get("sources", [])
        # Truncate to max
        c_copy["sources"] = sources[:max_sources_per_conclusion]
        c_copy["provenance_count"] = len(sources)
        enriched.append(c_copy)
    return enriched
