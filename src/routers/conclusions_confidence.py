"""Extended conclusion query with confidence scoring."""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src import crud, schemas
from src.dependencies import read_db
from src.exceptions import ValidationException
from src.security import require_auth
from src.utils.temporal_decay import apply_decay, get_decay_config
from src.utils.confidence import calculate_confidence, filter_by_confidence, enrich_with_provenance

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/conclusions",
    tags=["conclusions"],
    dependencies=[Depends(require_auth(workspace_name="workspace_id"))],
)


@router.post(
    "/query_with_confidence",
    response_model=list[dict[str, Any]],
)
async def query_conclusions_with_confidence(
    workspace_id: str = Path(...),
    body: schemas.ConclusionQuery = Body(
        ...,
        description="Semantic search parameters for Conclusions",
    ),
    min_confidence: float = Query(
        0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold (0.0-1.0)",
    ),
    include_provenance: bool = Query(
        True,
        description="Include source provenance in results",
    ),
    db: AsyncSession = read_db,
) -> list[dict[str, Any]]:
    """
    Query Conclusions with confidence scoring and filtering.
    
    Applies multi-signal confidence scoring based on:
    - Source credibility
    - Temporal freshness
    - Consensus (number of sources)
    
    Optionally filters by minimum confidence threshold.
    """
    from src.utils.temporal_decay import get_decay_config

    observer = None
    observed = None
    if body.filters:
        observer = body.filters.get("observer") or body.filters.get("observer_id")
        observed = body.filters.get("observed") or body.filters.get("observed_id")

    if not observer or not observed:
        raise ValidationException(
            "observer and observed must be specified for semantic search."
        )

    # Get raw conclusions
    documents = await crud.query_documents(
        db,
        workspace_name=workspace_id,
        query=body.query,
        observer=observer,
        observed=observed,
        filters=body.filters,
        max_distance=body.distance,
        top_k=body.top_k,
    )

    if not documents:
        return []

    # Apply temporal decay
    decay_config = get_decay_config()
    if decay_config["enabled"]:
        docs_dict = [
            {
                "id": d.id,
                "score": d.score or 0.0,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "text": d.text,
                "source_type": d.metadata.get("source_type", "conversation") if d.metadata else "conversation",
                "sources": d.metadata.get("sources", []) if d.metadata else [],
            }
            for d in documents
        ]
        docs_dict = apply_decay(
            docs_dict,
            half_life=decay_config["half_life_days"],
            min_weight=decay_config["min_weight"],
            max_age_days=decay_config["max_age_days"],
        )
        # Re-sort by decay-weighted score
        sorted_ids = [d["id"] for d in docs_dict]
        documents = sorted(
            documents,
            key=lambda d: sorted_ids.index(d.id) if d.id in sorted_ids else len(sorted_ids),
        )

    # Convert to dicts for confidence scoring
    conclusions_dict = []
    for d in documents:
        conclusions_dict.append({
            "id": d.id,
            "text": d.text,
            "score": d.score or 0.0,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "source_type": d.metadata.get("source_type", "conversation") if d.metadata else "conversation",
            "sources": d.metadata.get("sources", []) if d.metadata else [],
        })

    # Apply confidence scoring
    if min_confidence > 0.0:
        conclusions_dict, stats = filter_by_confidence(
            conclusions_dict,
            min_confidence=min_confidence,
            half_life_days=decay_config.get("half_life_days", 7.0),
        )
    else:
        # Just score without filtering
        for c in conclusions_dict:
            c["confidence"] = calculate_confidence(
                c,
                half_life_days=decay_config.get("half_life_days", 7.0),
            )
        stats = {
            "total_matched": len(conclusions_dict),
            "filtered_by_confidence": 0,
            "avg_confidence": sum(c.get("confidence", 0) for c in conclusions_dict) / len(conclusions_dict) if conclusions_dict else 0,
            "min_returned": min((c.get("confidence", 0) for c in conclusions_dict), default=0),
        }

    # Add provenance if requested
    if include_provenance:
        conclusions_dict = enrich_with_provenance(conclusions_dict)

    # Add stats to first result (or empty dict)
    if conclusions_dict:
        conclusions_dict[0]["_meta"] = stats
    else:
        conclusions_dict.append({"_meta": stats, "_empty": True})

    return conclusions_dict
