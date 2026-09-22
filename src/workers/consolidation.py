"""Enhanced consolidation worker with bidirectional memory extraction."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.dependencies import tracked_db
from src.kg.episodic_models import Episode, Insight, Summary
from src.memory.agent_model import AgentSelfModel, Lesson

logger = logging.getLogger(__name__)

# Configuration
MAX_QUEUE_DEPTH = 1000
SUMMARIZATION_BATCH_SIZE = 10
INSIGHT_EXTRACTION_INTERVAL_HOURS = 24
MAX_INSIGHT_AGE_DAYS = 365

# Lesson extraction patterns
CORRECTION_PATTERNS = [
    ("don't", "be more careful"),
    ("stop", "change behavior"),
    ("wrong", "correct approach"),
    ("incorrect", "use different method"),
    ("should have", "learn from mistake"),
    ("actually", "correct previous assumption"),
    ("no", "reconsider approach"),
    ("wrong command", "use correct command"),
    ("wrong flag", "use correct flag"),
    ("wrong path", "use correct path"),
]

PREFERENCE_PATTERNS = [
    ("be concise", "prefer concise responses"),
    ("be thorough", "prefer detailed responses"),
    ("use bullet points", "prefer bullet point format"),
    ("show code", "want code examples"),
    ("explain", "want explanations"),
    ("don't explain", "prefer direct answers"),
    ("quick", "want quick responses"),
    ("detailed", "want detailed responses"),
]


async def create_episode(
    session_id: str,
    workspace_name: str,
    user_id: str,
    message_count: int,
) -> str:
    """Create a new episode record."""
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
    """Generate summary for an episode.
    
    TODO: Integrate with LLM provider for real summarization.
    Currently creates placeholder summary.
    """
    # TODO: Call LLM to extract key points
    summary = Summary(
        episode_id=episode.id,
        key_points=[f"Episode {episode.id} processed"],
        decisions=[],
        open_questions=[],
        summary_text=f"Summary for episode {episode.id}",
    )
    db.add(summary)
    await db.commit()
    return summary


async def extract_lessons_from_episode(
    episode: Episode,
    agent_model: AgentSelfModel,
) -> list[Lesson]:
    """Extract lessons from episode transcript.
    
    This is a heuristic-based extractor. In production, this would
    use an LLM to analyze the conversation.
    """
    lessons = []
    
    # TODO: Read actual transcript from episode
    # For now, simulate extraction from metadata
    transcript_preview = f"Session {episode.session_id}: {episode.message_count} messages"
    
    for pattern, adaptation in CORRECTION_PATTERNS:
        if pattern in transcript_preview.lower():
            lesson = agent_model.add_lesson(
                trigger=pattern,
                adaptation=adaptation,
                confidence=0.5,  # Low confidence for heuristic extraction
                source="inferred",
                session_id=episode.session_id,
            )
            lessons.append(lesson)
    
    return lessons


async def process_episode_queue(db: AsyncSession, limit: int = 100) -> dict[str, int]:
    """Process pending episodes in the queue."""
    episodes = await get_pending_episodes(db, limit=limit)
    if not episodes:
        return {"processed": 0, "errors": 0}

    stats = {"processed": 0, "errors": 0}

    for episode in episodes[:limit]:
        try:
            episode.status = "summarizing"
            await db.commit()

            # Generate summary
            await generate_summary(episode, db)
            
            # Extract lessons for bidirectional memory
            agent_model = AgentSelfModel(
                agent_id="honcho_dialectic",
                workspace_name=episode.workspace_name,
            )
            lessons = await extract_lessons_from_episode(episode, agent_model)
            
            # TODO: Save agent model to database
            # For now, just log
            if lessons:
                logger.info(
                    "Extracted %d lessons from episode %s",
                    len(lessons), episode.id
                )

            episode.status = "summarized"
            episode.updated_at = datetime.now(UTC)
            await db.commit()
            stats["processed"] += 1

        except Exception as e:
            logger.error("Failed to process episode %s: %s", episode.id, e)
            episode.status = "error"
            await db.commit()
            stats["errors"] += 1

    return stats


async def extract_insights(db: AsyncSession) -> dict[str, int]:
    """Extract insights from recent summaries."""
    cutoff = datetime.now(UTC) - timedelta(days=7)
    stmt = select(Summary).where(Summary.created_at >= cutoff)
    result = await db.execute(stmt)
    summaries = list(result.scalars().all())

    if len(summaries) < 3:
        return {"insights_created": 0}

    # TODO: Implement actual insight extraction logic
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
    cutoff = datetime.now(UTC) - timedelta(days=MAX_INSIGHT_AGE_DAYS)
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
                stats = await process_episode_queue(db)
                if stats["processed"] > 0:
                    logger.info(
                        "Processed %d episodes, %d errors",
                        stats["processed"], stats["errors"]
                    )

                await extract_insights(db)
                purged = await purge_expired_insights(db)
                if purged > 0:
                    logger.info("Purged %d expired insights", purged)

        except Exception as e:
            logger.error("Consolidation worker error: %s", e, exc_info=True)

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
