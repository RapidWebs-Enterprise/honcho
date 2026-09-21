"""Episodic memory models for Honcho."""

from datetime import UTC, datetime

from nanoid import generate as generate_nanoid
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Episode(Base):
    """Raw message batch preserved for audit and consolidation."""

    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_nanoid)
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    workspace_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="raw")  # raw | summarizing | summarized | error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # Index for querying recent episodes
        {"sqlite_autoincrement": False},
    )


class Summary(Base):
    """LLM-extracted key points from an episode."""

    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_nanoid)
    episode_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    summary_text: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Insight(Base):
    """Cross-episode pattern detection."""

    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_nanoid)
    workspace_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    supporting_summary_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # Unique constraint to prevent duplicate insights
        # (workspace, topic, pattern_hash) — simplified here
        {"sqlite_autoincrement": False},
    )
