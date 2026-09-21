"""Tests for confidence scoring module."""

import pytest
from datetime import datetime, timezone, timedelta

from src.utils.confidence import (
    calculate_confidence,
    filter_by_confidence,
    enrich_with_provenance,
    SOURCE_CREDIBILITY,
)


class TestCalculateConfidence:
    """Test confidence calculation logic."""

    def test_tool_result_high_confidence(self):
        """Tool results should have high base confidence."""
        conclusion = {
            "source_type": "tool_result",
            "sources": [{"id": "test_1"}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        assert confidence > 0.8  # High due to tool source + recent

    def test_conversation_medium_confidence(self):
        """Conversations should have medium base confidence."""
        conclusion = {
            "source_type": "conversation",
            "sources": [{"id": "session_1"}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        assert 0.4 < confidence < 0.8

    def test_speculation_low_confidence(self):
        """Speculation should have low base confidence."""
        conclusion = {
            "source_type": "speculation",
            "sources": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        assert confidence < 0.5

    def test_temporal_decay(self):
        """Older conclusions should have lower freshness score."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent_date = datetime.now(timezone.utc).isoformat()

        old_conclusion = {
            "source_type": "conversation",
            "sources": [{"id": "test"}],
            "created_at": old_date,
        }
        recent_conclusion = {
            "source_type": "conversation",
            "sources": [{"id": "test"}],
            "created_at": recent_date,
        }

        old_conf = calculate_confidence(old_conclusion)
        recent_conf = calculate_confidence(recent_conclusion)

        assert old_conf < recent_conf

    def test_consensus_boost(self):
        """More sources should increase confidence."""
        single_source = {
            "source_type": "conversation",
            "sources": [{"id": "only_one"}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        multiple_sources = {
            "source_type": "conversation",
            "sources": [
                {"id": "source_1"},
                {"id": "source_2"},
                {"id": "source_3"},
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        single_conf = calculate_confidence(single_source)
        multi_conf = calculate_confidence(multiple_sources)

        assert multi_conf > single_conf

    def test_unknown_source_type_defaults(self):
        """Unknown source types should default to 0.5."""
        conclusion = {
            "source_type": "unknown_type",
            "sources": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        # Should use default 0.5 for unknown source
        assert 0.3 < confidence < 0.7

    def test_clamps_to_one(self):
        """Confidence should never exceed 1.0."""
        conclusion = {
            "source_type": "tool_result",
            "sources": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        assert confidence <= 1.0

    def test_clamps_to_zero(self):
        """Confidence should never go below 0.0."""
        conclusion = {
            "source_type": "speculation",
            "sources": [],
            "created_at": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),
        }
        confidence = calculate_confidence(conclusion)
        assert confidence >= 0.0

    def test_future_timestamp_clamped(self):
        """Future timestamps should be clamped to now."""
        future = (datetime.now(timezone.utc) + timedelta(days=100)).isoformat()
        conclusion = {
            "source_type": "conversation",
            "sources": [{"id": "test"}],
            "created_at": future,
        }
        confidence = calculate_confidence(conclusion)
        # Should not get artificial boost from future date
        assert confidence < 0.9


class TestFilterByConfidence:
    """Test confidence filtering."""

    def test_filters_below_threshold(self):
        """Should exclude conclusions below min_confidence."""
        conclusions = [
            {
                "source_type": "tool_result",
                "sources": [{"id": "s1"}],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "source_type": "speculation",
                "sources": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        filtered, stats = filter_by_confidence(
            conclusions,
            min_confidence=0.7
        )

        assert len(filtered) < len(conclusions)
        assert stats["filtered_by_confidence"] > 0

    def test_returns_stats(self):
        """Should return accurate statistics."""
        conclusions = [
            {
                "source_type": "tool_result",
                "sources": [{"id": "s1"}],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        filtered, stats = filter_by_confidence(conclusions)

        assert "total_matched" in stats
        assert "avg_confidence" in stats
        assert stats["total_matched"] == 1

    def test_empty_list(self):
        """Should handle empty input gracefully."""
        filtered, stats = filter_by_confidence([])
        assert filtered == []
        assert stats["total_matched"] == 0


class TestEnrichWithProvenance:
    """Test provenance enrichment."""

    def test_adds_provenance_count(self):
        """Should add provenance_count field."""
        conclusions = [
            {
                "source_type": "conversation",
                "sources": [{"id": "s1"}, {"id": "s2"}],
            }
        ]

        enriched = enrich_with_provenance(conclusions)
        assert "provenance_count" in enriched[0]
        assert enriched[0]["provenance_count"] == 2

    def test_truncates_sources(self):
        """Should truncate sources to max."""
        many_sources = [{"id": f"s{i}"} for i in range(10)]
        conclusions = [
            {
                "source_type": "conversation",
                "sources": many_sources,
            }
        ]

        enriched = enrich_with_provenance(
            conclusions,
            max_sources_per_conclusion=5
        )

        assert len(enriched[0]["sources"]) == 5
