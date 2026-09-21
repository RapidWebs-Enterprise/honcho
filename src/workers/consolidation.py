"""Async worker for episodic consolidation."""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.dependencies import tracked_db
from src.kg.episodic_models import Episode, Insight, Summary

logger = logging.getLogger(__name__)

# Configuration
MAX_QUEUE_DEPTH = 1000
SUMMARIZATION_BATCH_SIZE = 10
INSIGHT_EXTRACTION_INTERVAL_HOURS = 24
MAX_INSIGHT_AGE_DAYS = 365


async def create_episode(
    session_id: str,
    workspace_name: str,
    user_id: str,
    message_count: int,
) -> str:
    """Create a new episode record.

    Returns:
        Episode ID
    """
    async with tracked_db("episode_create") as db:
        episode = Episode(
            session_id=session_id,
            workspace_name=workspace_name,
            user_id=user_id,
            message_count=message_count,
            status="raw",
        )
        db.add(episode)
        await db.commit()
        await db.refresh(episode)
        logger.info("Created episode %s for session %s", episode.id, session_id)
        return episode.id


async def get_pending_episodes(db: AsyncSession, limit: int = 100) -> list[Episode]:
    """Get episodes pending summarization."""
    stmt = select(Episode).where(
        Episode.status.in_(["raw", "error"]),
    ).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def generate_summary(episode: Episode, db: AsyncSession) -> Summary:
    """Generate summary for an episode using LLM.

    Note: This is a stub implementation. In production, this would
    call an LLM to extract key points, decisions, and open questions.
    """
    # TODO: Integrate with LLM provider
    # For now, create a placeholder summary
    summary = Summary(
        episode_id=episode.id,
        key_points=[f"Episode {episode.id} created at {episode.created_at}"],
        decisions=[],
        open_questions=[],
        summary_text=f"Summary for episode {episode.id}",
    )
    db.add(summary)
    await db.commit()
    return summary


async def process_episode_queue(db: AsyncSession, limit: int = 100) -> dict[str, int]:
    """Process pending episodes in the queue.

    Returns:
        Stats dict with counts
    """
    episodes = await get_pending_episodes(db, limit=limit)
    if not episodes:
        return {"processed": 0, "errors": 0}

    stats = {"processed": 0, "errors": 0}

    for episode in episodes[:limit]:
        try:
            episode.status = "summarizing"
            await db.commit()

            await generate_summary(episode, db)

            episode.status = "summarized"
            episode.updated_at = datetime.now(timezone.utc)
            await db.commit()
            stats["processed"] += 1

        except Exception as e:
            logger.error("Failed to process episode %s: %s", episode.id, e)
            episode.status = "error"
            await db.commit()
            stats["errors"] += 1

    return stats


async def extract_insights(db: AsyncSession) -> dict[str, int]:
    """Extract insights from recent summaries.

    Returns:
        Stats dict with counts
    """
    # Get recent summaries (last 7 days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    stmt = select(Summary).where(Summary.created_at >= cutoff)
    result = await db.execute(stmt)
    summaries = list(result.scalars().all())

    if len(summaries) < 3:
        return {"insights_created": 0}

    # TODO: Implement actual insight extraction logic
    # For now, create a placeholder insight
    insight = Insight(
        workspace_name="default",
        topic="recent_activity",
        pattern=f"Detected {len(summaries)} summaries in last 7 days",
        confidence=0.5,
        supporting_summary_ids=[s.id for s in summaries[:5]],
    )
    db.add(insight)
    await db.commit()

    return {"insights_created": 1}


async def purge_expired_insights(db: AsyncSession) -> int:
    """Remove expired insights."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_INSIGHT_AGE_DAYS)
    stmt = select(Insight).where(
        Insight.expires_at != None,  # noqa: E711
        Insight.expires_at < cutoff,
    )
    result = await db.execute(stmt)
    expired = list(result.scalars().all())

    for insight in expired:
        insight.is_active = False
    await db.commit()

    return len(expired)


async def consolidation_worker() -> None:
    """Main worker loop for episodic consolidation."""
    logger.info("Episodic consolidation worker started")

    while True:
        try:
            async with tracked_db("consolidation_worker") as db:
                # Process pending episodes
                stats = await process_episode_queue(db)
                if stats["processed"] > 0:
                    logger.info("Processed %d episodes, %d errors",
                               stats["processed"], stats["errors"])

                # Run insight extraction periodically
                await extract_insights(db)

                # Purge expired insights
                purged = await purge_expired_insights(db)
                if purged > 0:
                    logger.info("Purged %d expired insights", purged)

        except Exception as e:
            logger.error("Consolidation worker error: %s", e, exc_info=True)

        # Sleep before next iteration
        await asyncio.sleep(60)


async def start_consolidation_worker() -> None:
    """Start the consolidation worker in background."""
    worker_task = asyncio.create_task(consolidation_worker())
    logger.info("Consolidation worker task created")
    return worker_task


async def stop_consolidation_worker(task: asyncio.Task) -> None:
    """Stop the consolidation worker."""
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("Consolidation worker stopped")
