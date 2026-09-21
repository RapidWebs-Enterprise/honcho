"""Tests for bidirectional memory system."""


from src.memory.agent_model import AgentSelfModel


class TestAgentSelfModel:
    """Test AgentSelfModel core functionality."""

    def test_create_model(self):
        """Test creating a new agent model."""
        model = AgentSelfModel(
            agent_id="test_agent",
            workspace_name="test_workspace",
        )
        assert model.agent_id == "test_agent"
        assert model.workspace_name == "test_workspace"
        assert model.lessons == []
        assert model.mistakes == []

    def test_add_lesson(self):
        """Test adding a lesson to the model."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        lesson = model.add_lesson(
            trigger="verbose",
            adaptation="be concise",
            confidence=0.9,
            session_id="session_123",
        )
        
        assert len(model.lessons) == 1
        assert model.lessons[0].trigger == "verbose"
        assert model.lessons[0].adaptation == "be concise"
        assert model.lessons[0].confidence == 0.9

    def test_add_mistake(self):
        """Test recording a mistake."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        mistake = model.add_mistake(
            description="Wrong command",
            correction="Use 'podman restart' not 'podman stop && start'",
            severity="high",
        )
        
        assert len(model.mistakes) == 1
        assert mistake.resolved is False

    def test_mark_mistake_resolved(self):
        """Test marking a mistake as resolved."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        mistake = model.add_mistake("desc", "corr")
        
        result = model.mark_mistake_resolved(0)
        assert result is True
        assert model.mistakes[0].resolved is True

    def test_get_applicable_lessons(self):
        """Test filtering lessons by query."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        model.add_lesson("verbose", "be concise")
        model.add_lesson("technical", "explain deeply")
        
        lessons = model.get_applicable_lessons("This is too verbose")
        assert len(lessons) == 1
        assert lessons[0].trigger == "verbose"

    def test_adapt_response(self):
        """Test response adaptation."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        model.add_lesson("verbose", "be concise")
        
        result = model.adapt_response(
            query="This is verbose",
            user_preferences={"style": "concise"}
        )
        
        assert "adaptations" in result
        assert len(result["adaptations"]) > 0

    def test_serialization(self):
        """Test model serialization/deserialization."""
        model = AgentSelfModel(agent_id="test", workspace_name="ws")
        model.add_lesson("trigger", "adaptation")
        
        data = model.to_dict()
        restored = AgentSelfModel.from_dict(data)
        
        assert restored.agent_id == model.agent_id
        assert len(restored.lessons) == 1
        assert restored.lessons[0].adaptation == "adaptation"


class TestBidirectionalIntegration:
    """Test integration between user and agent models."""

    def test_cross_model_inference(self):
        """Test inference from combined models."""
        from src.memory.user_model import UserMentalState
        
        user_model = UserMentalState(
            user_id="steven",
            preferences={"style": "concise"},
            emotional_state="frustrated",
        )
        
        agent_model = AgentSelfModel(
            agent_id="lucien",
            workspace_name="default",
        )
        agent_model.add_lesson("verbose", "be concise")
        
        # Inference should consider both models
        adaptations = agent_model.adapt_response(
            query="Help me deploy",
            user_preferences=user_model.preferences
        )
        
        # Should have adaptations from both lesson and preference
        assert len(adaptations["adaptations"]) >= 1
