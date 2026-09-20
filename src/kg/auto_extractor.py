"""Auto-Extraction Core Module.

Handles LLM-based entity/relationship extraction from messages
and persists results to the Knowledge Graph.
"""

import json
import logging
import uuid
from datetime import datetime

from src.config import ModelConfig, settings
from src.dependencies import tracked_db
from src.kg.extraction_prompt import KG_EXTRACTION_PROMPT
from src.kg.extraction_schema import KG_EXTRACTION_SCHEMA, validate_extraction_output
from src.kg.models import KGEntity, KGRelationship
from src.llm import honcho_llm_call
from src.llm.types import LLMTelemetryContext

logger = logging.getLogger(__name__)


class AutoExtractor:
    """Handles automatic KG entity/relationship extraction from messages."""

    def __init__(self):
        self._extraction_prompt = KG_EXTRACTION_PROMPT
        self._extraction_schema = KG_EXTRACTION_SCHEMA

    async def extract_from_messages(
        self,
        workspace_name: str,
        message_ids: list[str],
        session_names: list[str] | None = None,
    ) -> dict[str, int]:
        """Extract entities and relationships from a batch of messages.

        Args:
            workspace_name: Workspace to extract from
            message_ids: List of message public_ids to process
            session_names: Optional session names for context

        Returns:
            Dict with counts of entities/relationships created/updated
        """
        if not message_ids:
            return {"entities_created": 0, "entities_updated": 0, "relationships_created": 0}

        logger.info(
            "Starting auto-extraction for workspace %s: %d messages",
            workspace_name,
            len(message_ids),
        )

        start_time = datetime.utcnow()

        try:
            # Fetch messages from database
            messages = await self._fetch_messages(message_ids)
            if not messages:
                logger.warning("No messages found for IDs: %s", message_ids)
                return {"entities_created": 0, "entities_updated": 0, "relationships_created": 0}

            # Format messages for LLM
            formatted_messages = self._format_messages(messages)

            # Call LLM for extraction
            extraction_result = await self._call_extraction_llm(formatted_messages)

            # Validate output
            validate_extraction_output(extraction_result)

            # Persist to KG
            stats = await self._persist_extractions(
                workspace_name=workspace_name,
                entities=extraction_result.get("entities", []),
                relationships=extraction_result.get("relationships", []),
            )

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                "Auto-extraction completed for workspace %s in %.2fs: "
                "entities_created=%d, entities_updated=%d, relationships_created=%d",
                workspace_name,
                duration,
                stats["entities_created"],
                stats["entities_updated"],
                stats["relationships_created"],
            )

            return stats

        except Exception as e:
            logger.exception(
                "Auto-extraction failed for workspace %s: %s",
                workspace_name,
                e,
            )
            # Don't raise - don't block message ingestion
            return {"entities_created": 0, "entities_updated": 0, "relationships_created": 0, "error": str(e)}

    async def _fetch_messages(self, message_ids: list[str]) -> list[dict]:
        """Fetch message content by IDs."""
        async with tracked_db("auto_extraction.fetch_messages", read_only=True) as db:
            from sqlalchemy import select

            from src import models

            stmt = (
                select(models.Message)
                .where(models.Message.public_id.in_(message_ids))
                .order_by(models.Message.created_at.asc())
            )
            result = await db.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": m.public_id,
                    "content": m.content,
                    "peer_name": m.peer_name,
                    "session_name": m.session_name,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "metadata": m.h_metadata,
                }
                for m in messages
            ]

    def _format_messages(self, messages: list[dict]) -> str:
        """Format messages for LLM extraction prompt."""
        lines = []
        for msg in messages:
            timestamp = msg.get("created_at", "")
            peer = msg.get("peer_name", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{timestamp}] {peer}: {content}")
        return "\n".join(lines)

    async def _call_extraction_llm(self, formatted_messages: str) -> dict:
        """Call LLM to extract entities and relationships."""
        prompt = self._extraction_prompt.format(message=formatted_messages)

        # Get model config for extraction - use deriver model config
        deriver_config = settings.DERIVER.MODEL_CONFIG

        model_config = ModelConfig(
            provider=deriver_config.provider,
            model=deriver_config.model,
            base_url=deriver_config.base_url,
            api_key=deriver_config.api_key,
        )


        response = await honcho_llm_call(
            model_config=model_config,
            prompt=prompt,
            max_tokens=4000,
            temperature=0.1,
            json_mode=True,
            response_model=None,
            telemetry=LLMTelemetryContext(
                purpose="kg_extraction",
                workspace_name="auto_extraction",
            ),
        )

        # Parse JSON response
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse extraction JSON: %s", e)
            logger.debug("Raw response: %s", content)
            raise

    async def _persist_extractions(
        self,
        workspace_name: str,
        entities: list[dict],
        relationships: list[dict],
    ) -> dict[str, int]:
        """Persist extracted entities and relationships to the KG."""
        stats = {
            "entities_created": 0,
            "entities_updated": 0,
            "relationships_created": 0,
        }

        async with tracked_db("kg_auto_extraction.persist") as db:
            # Upsert entities
            for entity_data in entities:
                created = await self._upsert_entity(
                    db=db,
                    workspace_name=workspace_name,
                    entity_data=entity_data,
                )
                if created:
                    stats["entities_created"] += 1
                else:
                    stats["entities_updated"] += 1

            # Upsert relationships
            for rel_data in relationships:
                created = await self._upsert_relationship(
                    db=db,
                    workspace_name=workspace_name,
                    rel_data=rel_data,
                )
                if created:
                    stats["relationships_created"] += 1

            await db.commit()

        return stats

    async def _upsert_entity(
        self,
        db,
        workspace_name: str,
        entity_data: dict,
    ) -> bool:
        """Upsert entity. Returns True if created, False if updated."""
        from sqlalchemy import select

        from src.kg.entity_types import validate_entity_type

        try:
            validate_entity_type(entity_data.get("type", "unknown"))
        except Exception as e:
            logger.warning("Invalid entity type '%s' for '%s': %s",
                          entity_data.get("type"), entity_data.get("name"), e)
            return False

        name = entity_data.get("name", "").strip()
        if not name:
            return False

        entity_type = entity_data.get("type", "unknown")
        aliases = entity_data.get("aliases", [])

        # Try to find existing entity
        stmt = (
            select(KGEntity)
            .where(KGEntity.workspace_name == workspace_name)
            .where(KGEntity.name == name)
            .where(KGEntity.entity_type == entity_type)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            updated = False
            if aliases:
                # Merge aliases
                existing_aliases = set(existing.aliases or [])
                new_aliases = set(aliases)
                if not new_aliases.issubset(existing_aliases):
                    existing.aliases = list(existing_aliases | new_aliases)
                    updated = True
            if updated:
                await db.flush()
            return False  # Updated

        # Create new
        new_entity = KGEntity(
            id=str(uuid.uuid4()),
            workspace_name=workspace_name,
            name=name,
            entity_type=entity_type,
            aliases=aliases,
            confidence=0.8,  # Default confidence for auto-extracted
            peer_name=None,
            mention_count=1,
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(new_entity)
        await db.flush()
        return True  # Created

    async def _upsert_relationship(
        self,
        db,
        workspace_name: str,
        rel_data: dict,
    ) -> bool:
        """Upsert relationship. Returns True if created, False if already exists."""
        from sqlalchemy import select

        from src.kg.relationship_types import validate_relationship_type

        try:
            validate_relationship_type(rel_data.get("type", "related_to"))
        except Exception as e:
            logger.warning("Invalid relationship type '%s': %s",
                          rel_data.get("type"), e)
            return False

        source_name = rel_data.get("source", "").strip()
        target_name = rel_data.get("target", "").strip()
        rel_type = rel_data.get("type", "related_to")
        properties = rel_data.get("properties", {})

        if not source_name or not target_name:
            return False

        if source_name == target_name:
            return False

        # Find source entity
        from src.kg.models import KGEntity

        source_stmt = select(KGEntity).where(
            KGEntity.workspace_name == workspace_name,
            KGEntity.name == source_name,
        )
        source_result = await db.execute(source_stmt)
        source_entity = source_result.scalar_one_or_none()

        target_stmt = select(KGEntity).where(
            KGEntity.workspace_name == workspace_name,
            KGEntity.name == target_name,
        )
        target_result = await db.execute(target_stmt)
        target_entity = target_result.scalar_one_or_none()

        if not source_entity or not target_entity:
            logger.debug(
                "Relationship source/target not found: %s -> %s",
                source_name, target_name
            )
            return False

        # Check if relationship already exists
        stmt = select(KGRelationship).where(
            KGRelationship.workspace_name == workspace_name,
            KGRelationship.source_entity_id == source_entity.id,
            KGRelationship.target_entity_id == target_entity.id,
            KGRelationship.relationship_type == rel_type,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update properties if different
            if rel_data.get("properties") and rel_data["properties"] != existing.properties:
                existing.properties = rel_data["properties"]
                await db.flush()
            return False  # Updated

        # Create new
        new_rel = KGRelationship(
            id=str(uuid.uuid4()),
            workspace_name=workspace_name,
            source_entity_id=source_entity.id,
            target_entity_id=target_entity.id,
            relationship_type=rel_type,
            properties=properties or {},
            confidence=0.7,  # Default for auto-extracted
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(new_rel)
        await db.flush()
        return True  # Created


# Global instance
_auto_extractor: "AutoExtractor | None" = None


def get_auto_extractor() -> "AutoExtractor":
    """Get the global auto extractor instance."""
    global _auto_extractor
    if _auto_extractor is None:
        _auto_extractor = AutoExtractor()
    return _auto_extractor