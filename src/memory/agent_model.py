"""Agent self-model for bidirectional memory system."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    """A lesson learned by the agent from interaction."""
    
    trigger: str                    # What prompted the lesson
    adaptation: str                 # How agent should behave
    confidence: float = 0.7         # How confident we are
    source: str = "user_correction" # user_correction | inferred | explicit
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    session_id: str = ""            # Which session taught this
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "trigger": self.trigger,
            "adaptation": self.adaptation,
            "confidence": self.confidence,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Lesson:
        """Deserialize from dictionary."""
        ts = data.get("timestamp")
        if ts:
            data["timestamp"] = datetime.fromisoformat(ts)
        return cls(**data)


@dataclass
class Mistake:
    """A mistake made by the agent."""
    
    description: str
    correction: str
    severity: str = "medium"  # low | medium | high
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    
    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "correction": self.correction,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
        }


class AgentSelfModel:
    """Persistent model of agent's self-knowledge."""
    
    def __init__(
        self,
        agent_id: str,
        workspace_name: str,
        lessons: list[Lesson] | None = None,
        capabilities: dict[str, bool] | None = None,
        mistakes: list[Mistake] | None = None,
    ):
        self.agent_id = agent_id
        self.workspace_name = workspace_name
        self.lessons: list[Lesson] = lessons or []
        self.capabilities: dict[str, bool] = capabilities or {}
        self.mistakes: list[Mistake] = mistakes or []
        self.adaptation_count: int = 0
        self.last_updated: datetime = datetime.now(UTC)
    
    def add_lesson(
        self,
        trigger: str,
        adaptation: str,
        confidence: float = 0.7,
        source: str = "user_correction",
        session_id: str = "",
    ) -> Lesson:
        """Add a new lesson to the model."""
        lesson = Lesson(
            trigger=trigger,
            adaptation=adaptation,
            confidence=confidence,
            source=source,
            session_id=session_id,
        )
        self.lessons.append(lesson)
        self.last_updated = datetime.now(UTC)
        logger.info("Added lesson: %s → %s", trigger, adaptation)
        return lesson
    
    def add_mistake(self, description: str, correction: str, severity: str = "medium") -> Mistake:
        """Record a mistake made by the agent."""
        mistake = Mistake(description=description, correction=correction, severity=severity)
        self.mistakes.append(mistake)
        self.last_updated = datetime.now(UTC)
        logger.warning("Recorded mistake: %s", description)
        return mistake
    
    def mark_mistake_resolved(self, mistake_idx: int) -> bool:
        """Mark a mistake as resolved."""
        if 0 <= mistake_idx < len(self.mistakes):
            self.mistakes[mistake_idx].resolved = True
            self.last_updated = datetime.now(UTC)
            return True
        return False
    
    def get_applicable_lessons(self, query: str) -> list[Lesson]:
        """Get lessons relevant to current query."""
        query_lower = query.lower()
        applicable = []
        
        for lesson in self.lessons:
            # Check if trigger matches query
            if lesson.trigger.lower() in query_lower or lesson.source == "inferred":
                applicable.append(lesson)
        
        # Sort by confidence
        applicable.sort(key=lambda l: l.confidence, reverse=True)
        return applicable
    
    def adapt_response(self, query: str, user_preferences: dict) -> dict:
        """Generate adaptation recommendations based on models."""
        adaptations = []
        
        # Apply relevant lessons
        lessons = self.get_applicable_lessons(query)
        for lesson in lessons:
            adaptations.append({
                "type": "lesson",
                "behavior": lesson.adaptation,
                "confidence": lesson.confidence,
                "source": lesson.source,
            })
        
        # Apply user preferences
        if user_preferences.get("style") == "concise":
            adaptations.append({
                "type": "preference",
                "behavior": "Keep responses brief",
                "confidence": 0.9,
            })
        
        if user_preferences.get("format") == "bullet_points":
            adaptations.append({
                "type": "preference",
                "behavior": "Use bullet points",
                "confidence": 0.9,
            })
        
        self.adaptation_count += len(adaptations)
        return {"adaptations": adaptations}
    
    def to_dict(self) -> dict:
        """Serialize model to dictionary."""
        return {
            "agent_id": self.agent_id,
            "workspace_name": self.workspace_name,
            "lessons": [l.to_dict() for l in self.lessons],
            "capabilities": self.capabilities,
            "mistakes": [m.to_dict() for m in self.mistakes],
            "adaptation_count": self.adaptation_count,
            "last_updated": self.last_updated.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> AgentSelfModel:
        """Deserialize model from dictionary."""
        lessons = [Lesson.from_dict(l) for l in data.get("lessons", [])]
        mistakes = [Mistake(**m) for m in data.get("mistakes", [])]
        
        model = cls(
            agent_id=data.get("agent_id", ""),
            workspace_name=data.get("workspace_name", ""),
            lessons=lessons,
            capabilities=data.get("capabilities", {}),
            mistakes=mistakes,
        )
        model.adaptation_count = data.get("adaptation_count", 0)
        ts = data.get("last_updated")
        if ts:
            model.last_updated = datetime.fromisoformat(ts)
        return model


class AgentModelStore:
    """Persistent storage for AgentSelfModel instances."""
    
    def __init__(self, base_path: str):
        self.base_path = base_path
        self._models: dict[str, AgentSelfModel] = {}
    
    def get_or_create(self, agent_id: str, workspace_name: str) -> AgentSelfModel:
        """Get existing model or create new one."""
        key = f"{workspace_name}:{agent_id}"
        if key not in self._models:
            self._models[key] = AgentSelfModel(
                agent_id=agent_id,
                workspace_name=workspace_name,
            )
        return self._models[key]
    
    def save(self, model: AgentSelfModel) -> None:
        """Save model to persistent storage."""
        # In production: write to database
        # For now: in-memory cache
        key = f"{model.workspace_name}:{model.agent_id}"
        self._models[key] = model
        logger.debug("Saved agent model for %s", key)
    
    def load(self, agent_id: str, workspace_name: str) -> AgentSelfModel | None:
        """Load model from persistent storage."""
        key = f"{workspace_name}:{agent_id}"
        return self._models.get(key)
