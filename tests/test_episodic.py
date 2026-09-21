"""Tests for episodic consolidation module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.kg.episodic_models import Episode, Insight, Summary


class TestEpisodeModel:
    """Test Episode data model."""

    def test_episode_creation(self):
        """Test creating an episode."""
        episode = Episode(
            session_id="test_session",
            workspace_name="test_workspace",
            user_id="test_user",
            message_count=10,
        )
        assert episode.status == "raw"
        assert episode.message_count == 10

    def test_episode_status_transitions(self):
        """Test episode status transitions."""
        episode = Episode()
        assert episode.status == "raw"

        episode.status = "summarizing"
        assert episode.status == "summarizing"

        episode.status = "summarized"
        assert episode.status == "summarized"

        episode.status = "error"
        assert episode.status == "error"


class TestSummaryModel:
    """Test Summary data model."""

    def test_summary_creation(self):
        """Test creating a summary."""
        summary = Summary(
            episode_id="ep_123",
            key_points=["Point 1", "Point 2"],
            decisions=["Decision 1"],
            open_questions=["Question 1"],
        )
        assert len(summary.key_points) == 2
        assert len(summary.decisions) == 1
        assert len(summary.open_questions) == 1


class TestInsightModel:
    """Test Insight data model."""

    def test_insight_creation(self):
        """Test creating an insight."""
        insight = Insight(
            workspace_name="test",
            topic="user_preferences",
            pattern="User prefers concise responses",
            confidence=0.85,
            supporting_summary_ids=["s1", "s2"],
        )
        assert insight.confidence == 0.85
        assert insight.is_active is True

    def test_insight_expiration(self):
        """Test insight expiration."""
        insight = Insight()
        # Set expiry to past
        insight.expires_at = datetime.now(UTC) - timedelta(days=1)
        assert insight.expires_at < datetime.now(UTC)


class TestEpisodicWorker:
    """Test episodic worker functions."""

    @pytest.mark.asyncio
    async def test_process_episode_queue_empty(self):
        """Test processing empty queue."""
        from src.workers.consolidation import process_episode_queue

        # Mock database session
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=[])))

        stats = await process_episode_queue(mock_db)
        assert stats["processed"] == 0

    @pytest.mark.asyncio
    async def test_purge_expired_insights(self):
        """Test purging expired insights."""
        from src.workers.consolidation import purge_expired_insights

        mock_db = AsyncMock()

        # Mock expired insight
        expired_insight = Insight()
        expired_insight.expires_at = datetime.now(UTC) - timedelta(days=10)
        expired_insight.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expired_insight]
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await purge_expired_insights(mock_db)
        assert count == 1
        assert expired_insight.is_active is False
