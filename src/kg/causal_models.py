"""Causal relationship models for the Knowledge Graph."""

from datetime import UTC, datetime

from nanoid import generate as generate_nanoid
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KGCausalRelationship(Base):
    """A causal relationship between two entities (cause → effect).

    Unlike regular KGRelationship which captures any typed relation,
    this model is specifically for causal inference:
    - "Because of X, Y happened"
    - "X caused Y"
    - "Y resulted from X"

    Supports bidirectional traversal:
    - Forward: "What did X cause?" (outgoing)
    - Reverse: "What caused Y?" (incoming)
    """

    __tablename__ = "kg_causal_relationships"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=generate_nanoid
    )
    workspace_name: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.name"), nullable=False
    )
    source_entity_id: Mapped[str] = mapped_column(
        String, ForeignKey("kg_entities.id"), nullable=False, index=True
    )
    target_entity_id: Mapped[str] = mapped_column(
        String, ForeignKey("kg_entities.id"), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_text: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow
    )

    __table_args__ = (
        Index("idx_causal_workspace_source", "workspace_name", "source_entity_id"),
        Index("idx_causal_workspace_target", "workspace_name", "target_entity_id"),
        Index("idx_causal_valid", "workspace_name", "valid_from", "valid_to"),
    )

    @property
    def is_current(self) -> bool:
        """Check if this causal relationship is currently valid."""
        if self.valid_to is None:
            return True
        return self.valid_to > _utcnow()
