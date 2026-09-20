"""Tests for temporal decay functionality."""

from datetime import UTC, datetime, timedelta

from src.utils.temporal_decay import apply_decay, calculate_decay, get_decay_config


class TestCalculateDecay:
    """Test decay weight calculation."""

    def test_fresh_conclusion(self):
        """Fresh conclusion should have weight ~1.0."""
        weight = calculate_decay(0.0)
        assert 0.99 < weight <= 1.0

    def test_one_half_life(self):
        """After one half-life, weight should be ~0.5."""
        weight = calculate_decay(7.0, half_life=7.0)
        assert 0.49 < weight < 0.51

    def test_two_half_lives(self):
        """After two half-lives, weight should be ~0.25."""
        weight = calculate_decay(14.0, half_life=7.0)
        assert 0.24 < weight < 0.26

    def test_custom_half_life(self):
        """Should respect custom half-life."""
        weight = calculate_decay(1.0, half_life=1.0)
        assert 0.49 < weight < 0.51

    def test_zero_half_life_fallback(self):
        """Zero half-life should return 1.0 (no decay)."""
        weight = calculate_decay(100.0, half_life=0)
        assert weight == 1.0

    def test_old_conclusion_min_weight(self):
        """Very old conclusions approach 0."""
        weight = calculate_decay(365.0, half_life=7.0)
        assert weight < 0.001


class TestApplyDecay:
    """Test decay application to conclusion lists."""

    def test_sorts_by_combined_score(self):
        """Should sort by semantic score * decay weight."""
        now = datetime.now(UTC)

        conclusions = [
            {
                "id": "old",
                "score": 0.9,
                "created_at": now - timedelta(days=30),
            },
            {
                "id": "new",
                "score": 0.7,
                "created_at": now - timedelta(hours=1),
            },
        ]

        result = apply_decay(conclusions, half_life=7.0, min_weight=0.01)

        # Newer conclusion should rank higher despite lower semantic score
        assert result[0]["id"] == "new"
        assert result[1]["id"] == "old"

    def test_preserves_original_scores(self):
        """Should not modify original 'score' field."""
        now = datetime.now(UTC)

        conclusions = [
            {
                "id": "test",
                "score": 0.8,
                "created_at": now,
            }
        ]

        result = apply_decay(conclusions)

        assert result[0]["score"] == 0.8
        assert "_decay_weight" in result[0]

    def test_handles_missing_timestamps(self):
        """Should handle conclusions without timestamps."""
        conclusions = [
            {"id": "no_time", "score": 0.9},
            {"id": "with_time", "score": 0.7, "created_at": datetime.now(UTC)},
        ]

        result = apply_decay(conclusions)

        # Both should get weights
        assert all("_decay_weight" in c for c in result)

    def test_max_age_floor(self):
        """Older than max_age_days should get min_weight."""
        now = datetime.now(UTC)

        conclusions = [
            {
                "id": "ancient",
                "score": 0.9,
                "created_at": now - timedelta(days=400),
            }
        ]

        result = apply_decay(conclusions, max_age_days=365, min_weight=0.01)

        assert result[0]["_decay_weight"] == 0.01


class TestGetDecayConfig:
    """Test configuration loading."""

    def test_default_config(self):
        """Should return sensible defaults."""
        config = get_decay_config()

        assert config["enabled"] is True
        assert config["half_life_days"] == 7
        assert config["min_weight"] == 0.01
        assert config["max_age_days"] == 365
