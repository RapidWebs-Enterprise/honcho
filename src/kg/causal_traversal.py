"""Causal traversal and query tools for the Knowledge Graph."""

import logging
from collections import deque
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.kg.causal_models import KGCausalRelationship
from src.kg.models import KGEntity

logger = logging.getLogger(__name__)

# Hard limit on traversal depth to prevent DoS
MAX_CAUSAL_DEPTH = 5


async def get_causal_chain(
    db: AsyncSession,
    workspace_name: str,
    entity_name: str,
    direction: str = "both",
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """Get causal chain for an entity.

    Args:
        db: Database session
        workspace_name: Workspace identifier
        entity_name: Starting entity name
        direction: "outgoing" (causes), "incoming" (effects), or "both"
        max_depth: Maximum traversal depth (capped at MAX_CAUSAL_DEPTH)

    Returns:
        List of causal relationships with entity info
    """
    # Resolve entity
    stmt = select(KGEntity).where(
        KGEntity.workspace_name == workspace_name,
        KGEntity.name == entity_name,
    )
    result = await db.execute(stmt)
    entity = result.scalar_one_or_none()

    if not entity:
        return []

    # Clamp depth
    effective_depth = min(max_depth, MAX_CAUSAL_DEPTH)

    # BFS traversal
    visited: set[str] = set()
    queue: deque[tuple[str, int, list[str]]] = deque()
    queue.append((entity.id, 0, []))
    visited.add(entity.id)

    results: list[dict[str, Any]] = []

    while queue:
        current_id, depth, path = queue.popleft()

        if depth >= effective_depth:
            continue

        # Get causal relationships
        if direction in ("outgoing", "both"):
            # Forward: current is cause
            stmt = select(KGCausalRelationship).where(
                KGCausalRelationship.workspace_name == workspace_name,
                KGCausalRelationship.source_entity_id == current_id,
                KGCausalRelationship.valid_to.is_(None) |
                (KGCausalRelationship.valid_to > datetime.now(datetime.timezone.utc)),
            )
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                if rel.target_entity_id not in visited:
                    visited.add(rel.target_entity_id)
                    results.append({
                        "type": "causal_outgoing",
                        "from": entity_name if depth == 0 else None,
                        "cause": current_id,
                        "effect": rel.target_entity_id,
                        "confidence": rel.confidence,
                        "evidence": rel.evidence_text,
                        "depth": depth + 1,
                        "path": path + [f"{entity_name}→{rel.target_entity_id}"],
                    })
                    # Get target entity name
                    ent_stmt = select(KGEntity).where(
                        KGEntity.id == rel.target_entity_id
                    )
                    ent_result = await db.execute(ent_stmt)
                    target_ent = ent_result.scalar_one_or_none()
                    if target_ent:
                        queue.append((rel.target_entity_id, depth + 1, path + [f"{entity_name}→{target_ent.name}"]))

        if direction in ("incoming", "both"):
            # Reverse: current is effect
            stmt = select(KGCausalRelationship).where(
                KGCausalRelationship.workspace_name == workspace_name,
                KGCausalRelationship.target_entity_id == current_id,
                KGCausalRelationship.valid_to.is_(None) |
                (KGCausalRelationship.valid_to > datetime.now(datetime.timezone.utc)),
            )
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                if rel.source_entity_id not in visited:
                    visited.add(rel.source_entity_id)
                    results.append({
                        "type": "causal_incoming",
                        "from": rel.source_entity_id,
                        "effect": current_id,
                        "confidence": rel.confidence,
                        "evidence": rel.evidence_text,
                        "depth": depth + 1,
                        "path": path + [f"{rel.source_entity_id}→{entity_name}"],
                    })
                    # Get source entity name
                    ent_stmt = select(KGEntity).where(
                        KGEntity.id == rel.source_entity_id
                    )
                    ent_result = await db.execute(ent_stmt)
                    source_ent = ent_result.scalar_one_or_none()
                    if source_ent:
                        queue.append((rel.source_entity_id, depth + 1, path + [f"{source_ent.name}→{entity_name}"]))

    return results


async def find_root_causes(
    db: AsyncSession,
    workspace_name: str,
    entity_name: str,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """Find root causes for an entity (reverse causal traversal).

    Args:
        db: Database session
        workspace_name: Workspace identifier
        entity_name: Target entity
        max_depth: Maximum traversal depth

    Returns:
        List of root cause chains
    """
    return await get_causal_chain(
        db, workspace_name, entity_name,
        direction="incoming",
        max_depth=max_depth
    )


async def find_downstream_effects(
    db: AsyncSession,
    workspace_name: str,
    entity_name: str,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """Find downstream effects of an entity (forward causal traversal).

    Args:
        db: Database session
        workspace_name: Workspace identifier
        entity_name: Source entity
        max_depth: Maximum traversal depth

    Returns:
        List of effect chains
    """
    return await get_causal_chain(
        db, workspace_name, entity_name,
        direction="outgoing",
        max_depth=max_depth
    )
