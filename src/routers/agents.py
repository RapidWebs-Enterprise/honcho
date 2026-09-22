"""API endpoints for agent self-model management."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.dependencies import read_db
from src.memory.agent_model import AgentSelfModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents",
    tags=["agents"],
)


@router.get("/{agent_id}/model")
async def get_agent_model(
    workspace_id: str = Path(...),
    agent_id: str = Path(...),
    include_lessons: bool = Query(True),
    include_mistakes: bool = Query(True),
    db: AsyncSession = read_db,
) -> dict[str, Any]:
    """Get agent self-model.
    
    Returns the agent's learned lessons, capabilities, and mistakes.
    """
    # TODO: Load from database
    # For now, create in-memory model
    model = AgentSelfModel(
        agent_id=agent_id,
        workspace_name=workspace_id,
    )
    
    result = model.to_dict()
    
    if not include_lessons:
        result["lessons"] = []
    if not include_mistakes:
        result["mistakes"] = []
    
    return result


@router.post("/{agent_id}/feedback")
async def submit_agent_feedback(
    workspace_id: str = Path(...),
    agent_id: str = Path(...),
    feedback: dict[str, Any] = Body(
        ...,
        description="User feedback about agent behavior",
    ),
    db: AsyncSession = read_db,
) -> dict[str, str]:
    """Submit feedback about agent behavior.
    
    User can correct agent behavior, which gets stored as a lesson.
    """
    trigger = feedback.get("trigger", "")
    correction = feedback.get("correction", "")
    
    if not trigger or not correction:
        return {"error": "trigger and correction are required"}
    
    # TODO: Save to database
    logger.info(
        "Agent feedback: trigger='%s' correction='%s'",
        trigger, correction
    )
    
    return {"status": "stored", "trigger": trigger}


@router.get("/{agent_id}/adaptations")
async def get_adaptations(
    workspace_id: str = Path(...),
    agent_id: str = Path(...),
    query: str = Query(..., description="Current user query"),
    db: AsyncSession = read_db,
) -> dict[str, Any]:
    """Get recommended adaptations for current query.
    
    Combines user preferences and agent lessons to suggest behavior adjustments.
    """
    # TODO: Load both user and agent models
    agent_model = AgentSelfModel(
        agent_id=agent_id,
        workspace_name=workspace_id,
    )
    
    # Mock user preferences (would come from UserMentalState)
    user_preferences = {
        "style": "concise",
        "format": "bullet_points",
    }
    
    adaptations = agent_model.adapt_response(query, user_preferences)
    
    return adaptations


@router.post("/lessons")
async def add_lesson(
    workspace_id: str = Path(...),
    lesson: dict[str, Any] = Body(
        ...,
        description="Lesson to add",
    ),
    db: AsyncSession = read_db,
) -> dict[str, str]:
    """Manually add a lesson to agent model.
    
    Useful for one-time corrections or system-level lessons.
    """
    trigger = lesson.get("trigger", "")
    adaptation = lesson.get("adaptation", "")
    confidence = lesson.get("confidence", 0.7)
    
    if not trigger or not adaptation:
        return {"error": "trigger and adaptation are required"}
    
    # TODO: Save to database
    logger.info("Manual lesson added: %s → %s", trigger, adaptation)
    
    return {"status": "stored"}
