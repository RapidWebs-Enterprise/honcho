"""HTTP endpoints for episodic memory management."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.kg.episodic_worker import (
    create_episode,
    extract_insights,
    get_pending_episodes,
    process_episode_queue,
    purge_expired_insights,
)

from src.dependencies import read_db
from src.kg.episodic_models import Episode, Summary

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/episodes",
    tags=["episodes"],
)


@router.post("")
async def create_episode_endpoint(
    workspace_id: str = Path(...),
    session_id: str = Body(..., embed=True),
    user_id: str = Body("default", embed=True),
    message_count: int = Body(0, embed=True),
    db: AsyncSession = read_db,
) -> dict[str, str]:
    """Create a new episode."""
    episode_id = await create_episode(
        session_id=session_id,
        workspace_name=workspace_id,
        user_id=user_id,
        message_count=message_count,
    )
    return {"episode_id": episode_id}


@router.get("/pending")
async def list_pending_episodes(
    workspace_id: str = Path(...),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = read_db,
) -> list[dict[str, Any]]:
    """List episodes pending summarization."""
    episodes = await get_pending_episodes(db, limit=limit)
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "status": e.status,
            "message_count": e.message_count,
            "created_at": e.created_at.isoformat(),
        }
        for e in episodes
    ]


@router.post("/process")
async def process_episodes_endpoint(
    workspace_id: str = Path(...),
    batch_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = read_db,
) -> dict[str, int]:
    """Process pending episodes."""
    stats = await process_episode_queue(db, batch_size=batch_size)
    return stats


@router.post("/insights/extract")
async def extract_insights_endpoint(
    workspace_id: str = Path(...),
    db: AsyncSession = read_db,
) -> dict[str, int]:
    """Trigger insight extraction."""
    stats = await extract_insights(db)
    return stats


@router.delete("/insights/expired")
async def purge_expired_insights_endpoint(
    workspace_id: str = Path(...),
    db: AsyncSession = read_db,
) -> dict[str, int]:
    """Purge expired insights."""
    count = await purge_expired_insights(db)
    return {"purged": count}


@router.get("")
async def list_episodes(
    workspace_id: str = Path(...),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = read_db,
) -> list[dict[str, Any]]:
    """List episodes with optional filtering."""
    from sqlalchemy import select

    stmt = select(Episode).where(Episode.workspace_name == workspace_id)
    if status:
        stmt = stmt.where(Episode.status == status)
    stmt = stmt.order_by(Episode.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    episodes = list(result.scalars().all())

    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "user_id": e.user_id,
            "message_count": e.message_count,
            "status": e.status,
            "created_at": e.created_at.isoformat(),
        }
        for e in episodes
    ]


@router.get("/{episode_id}")
async def get_episode(
    workspace_id: str = Path(...),
    episode_id: str = Path(...),
    db: AsyncSession = read_db,
) -> dict[str, Any]:
    """Get episode details."""
    from sqlalchemy import select

    stmt = select(Episode).where(
        Episode.id == episode_id,
        Episode.workspace_name == workspace_id,
    )
    result = await db.execute(stmt)
    episode = result.scalar_one_or_none()

    if not episode:
        return {"error": "Episode not found"}

    # Get related summary
    summary_stmt = select(Summary).where(Summary.episode_id == episode_id)
    summary_result = await db.execute(summary_stmt)
    summary = summary_result.scalar_one_or_none()

    return {
        "id": episode.id,
        "session_id": episode.session_id,
        "user_id": episode.user_id,
        "message_count": episode.message_count,
        "status": episode.status,
        "created_at": episode.created_at.isoformat(),
        "summary": {
            "key_points": summary.key_points if summary else [],
            "decisions": summary.decisions if summary else [],
        } if summary else None,
    }
