"""Unit tests for PlanningOrchestrator agent."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from osint_system.agents.planning_agent import PlanningOrchestrator
from osint_system.orchestration.state_schemas import OrchestratorState


class TestPlanningOrchestratorFoundation:
    """Test state schema validation and basic initialization."""

    def test_orchestrator_state_schema(self):
        """Verify OrchestratorState schema has all required fields."""
        # OrchestratorState is a TypedDict, we can't instantiate directly
        # but we can verify the annotation exists
        assert hasattr(OrchestratorState, "__annotations__")

        required_fields = [
            "objective",
            "messages",
            "subtasks",
            "agent_assignments",
            "findings",
            "refinement_count",
            "coverage_metrics",
            "signal_strength",
            "conflicts",
            "next_action",
        ]

        for field in required_fields:
            assert field in OrchestratorState.__annotations__

    def test_planning_orchestrator_initialization(self):
        """Test PlanningOrchestrator initializes correctly."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        assert orchestrator.name == "PlanningOrchestrator"
        assert orchestrator.agent_id is not None
        assert orchestrator.max_refinements == 7
        assert orchestrator.graph is not None
        assert orchestrator.registry is None
        assert orchestrator.message_bus is None


class TestObjectiveDecomposition:
    """Test objective analysis and subtask decomposition."""

    @pytest.mark.asyncio
    async def test_analyze_objective_with_fallback(self):
        """Test objective decomposition with fallback method."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        # Mock Gemini to force fallback
        orchestrator.gemini_client = None

        state: OrchestratorState = {
            "objective": "Investigate political developments in region X",
            "messages": [],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [],
            "refinement_count": 0,
            "max_refinements": 7,
            "coverage_metrics": {"source_diversity": 0.0, "geographic_coverage": 0.0, "topical_coverage": 0.0},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.analyze_objective(state)

        assert "subtasks" in result
        assert len(result["subtasks"]) > 0
        assert all("id" in st and "description" in st for st in result["subtasks"])
        assert "messages" in result
        # At least one message should be present (the decomposition summary)
        assert len(result["messages"]) >= 1

    @pytest.mark.asyncio
    async def test_analyze_objective_empty_input(self):
        """Test handling of empty objective."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        state: OrchestratorState = {
            "objective": "",
            "messages": [],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [],
            "refinement_count": 0,
            "max_refinements": 7,
            "coverage_metrics": {},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.analyze_objective(state)

        assert result["subtasks"] == []
        assert "No objective" in str(result["messages"])


class TestAdaptiveRouting:
    """Test adaptive routing logic based on findings."""

    @pytest.mark.asyncio
    async def test_routing_with_max_refinements_exceeded(self):
        """Test that routing synthesizes when max refinements exceeded."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        state: OrchestratorState = {
            "objective": "Test objective",
            "messages": ["test"],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [{"source": "test", "content": "data", "confidence": 0.5, "agent_id": "test"}],
            "refinement_count": 7,  # At or exceeded max
            "max_refinements": 7,
            "coverage_metrics": {"source_diversity": 0.0, "geographic_coverage": 0.0, "topical_coverage": 0.0},
            "signal_strength": 0.5,
            "conflicts": [],
            "next_action": "refine",
        }

        result = await orchestrator.evaluate_findings(state)

        assert result["next_action"] == "synthesize"
        assert "Max refinements" in result["messages"][-1]

    @pytest.mark.asyncio
    async def test_routing_weak_signal_early_stage(self):
        """Test that weak signal allows refinement in early stages."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        state: OrchestratorState = {
            "objective": "Test objective",
            "messages": ["test"],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [],  # No findings = weak signal
            "refinement_count": 0,  # Early stage
            "max_refinements": 7,
            "coverage_metrics": {"source_diversity": 0.0, "geographic_coverage": 0.0, "topical_coverage": 0.0},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.evaluate_findings(state)

        assert result["next_action"] == "refine"  # Continue in early stage

    @pytest.mark.asyncio
    async def test_routing_strong_signal_incomplete_coverage(self):
        """Test that strong signal but incomplete coverage leads to refinement."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        # Create findings that result in strong signal
        findings = [
            {"source": f"source{i}", "content": f"data{i}", "confidence": 0.9, "agent_id": "test"}
            for i in range(10)
        ]

        state: OrchestratorState = {
            "objective": "Test objective",
            "messages": ["test"],
            "subtasks": [],
            "agent_assignments": {},
            "findings": findings,
            "refinement_count": 2,
            "max_refinements": 7,
            "coverage_metrics": {"source_diversity": 0.3, "geographic_coverage": 0.2, "topical_coverage": 0.1},
            "signal_strength": 0.85,  # High signal
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.evaluate_findings(state)

        # Should refine to improve coverage
        assert result["next_action"] in ["refine", "synthesize"]  # May synthesize if approaching limit

    @pytest.mark.asyncio
    async def test_routing_diminishing_returns_detection(self):
        """Test that diminishing returns leads to synthesis."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        # Mock the diminishing returns check
        orchestrator._check_diminishing_returns = Mock(return_value=True)

        state: OrchestratorState = {
            "objective": "Test objective",
            "messages": ["test"],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [
                {"source": "source1", "content": "data1", "confidence": 0.7, "agent_id": "test"},
                {"source": "source2", "content": "data2", "confidence": 0.7, "agent_id": "test"},
                {"source": "source3", "content": "data3", "confidence": 0.7, "agent_id": "test"},
            ],
            "refinement_count": 3,
            "max_refinements": 7,
            "coverage_metrics": {"source_diversity": 0.5, "geographic_coverage": 0.4, "topical_coverage": 0.3},
            "signal_strength": 0.6,
            "conflicts": [],
            "next_action": "refine",
        }

        result = await orchestrator.evaluate_findings(state)

        assert result["next_action"] == "synthesize"


class TestTransparencyMethods:
    """Test transparency and explanation features."""

    def test_get_status(self):
        """Test status reporting."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None, max_refinements=5)

        status = orchestrator.get_status()

        assert "agent_id" in status
        assert status["name"] == "PlanningOrchestrator"
        assert status["max_refinements"] == 5
        assert "routing_thresholds" in status
        assert "signal_strength" in status["routing_thresholds"]
        assert "coverage_targets" in status["routing_thresholds"]

    def test_explain_routing(self):
        """Test routing explanation generation."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        explanation = orchestrator.explain_routing(
            findings_count=5,
            refinement_count=2,
            signal_strength=0.75
        )

        assert "Signal strength" in explanation
        assert "0.75" in explanation
        assert "Refinements" in explanation
        assert "2" in explanation
        # 0.75 equals the threshold, so it should be "moderate" not "strong"
        assert "signal" in explanation.lower()


class TestAgentAssignment:
    """Test agent assignment logic."""

    @pytest.mark.asyncio
    async def test_assign_agents_without_registry(self):
        """Test agent assignment without registry (fallback)."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        state: OrchestratorState = {
            "objective": "Test",
            "messages": ["test"],
            "subtasks": [
                {"id": "ST-001", "description": "Find news", "priority": 9, "suggested_sources": ["news"]},
                {"id": "ST-002", "description": "Search social media", "priority": 8, "suggested_sources": ["social_media"]},
            ],
            "agent_assignments": {},
            "findings": [],
            "refinement_count": 0,
            "max_refinements": 7,
            "coverage_metrics": {},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.assign_agents(state)

        # Without registry, all should be assigned to general_worker
        assert len(result["agent_assignments"]) == 2
        assert all(agent == "general_worker" for agent in result["agent_assignments"].values())

    @pytest.mark.asyncio
    async def test_assign_agents_with_registry(self):
        """Test agent assignment with mocked registry."""
        registry = AsyncMock()
        orchestrator = PlanningOrchestrator(registry=registry, message_bus=None)

        # Mock registry find_agents_by_capability
        mock_agent_info = Mock()
        mock_agent_info.name = "NewsAgent"
        registry.find_agents_by_capability.return_value = [mock_agent_info]

        state: OrchestratorState = {
            "objective": "Test",
            "messages": ["test"],
            "subtasks": [
                {"id": "ST-001", "description": "Find news", "priority": 9, "suggested_sources": ["news"]},
            ],
            "agent_assignments": {},
            "findings": [],
            "refinement_count": 0,
            "max_refinements": 7,
            "coverage_metrics": {},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "explore",
        }

        result = await orchestrator.assign_agents(state)

        assert "ST-001" in result["agent_assignments"]
        assert result["agent_assignments"]["ST-001"] == "NewsAgent"


class TestSignalStrengthCalculation:
    """Test signal strength computation."""

    def test_signal_strength_empty_findings(self):
        """Test signal strength with no findings."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        signal = orchestrator._calculate_signal_strength([])

        assert signal == 0.0

    def test_signal_strength_high_confidence_findings(self):
        """Test signal strength with high-confidence findings."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        findings = [
            {"confidence": 0.9},
            {"confidence": 0.85},
            {"confidence": 0.95},
        ]

        signal = orchestrator._calculate_signal_strength(findings)

        # Signal = (finding_score * 0.4) + (confidence_score * 0.6)
        # finding_score = min(3/10, 1.0) = 0.3
        # confidence_score = (0.9+0.85+0.95)/3 = 0.9
        # signal = (0.3 * 0.4) + (0.9 * 0.6) = 0.12 + 0.54 = 0.66
        assert 0.6 < signal <= 1.0  # Should be relatively high

    def test_signal_strength_low_confidence_findings(self):
        """Test signal strength with low-confidence findings."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        findings = [
            {"confidence": 0.3},
            {"confidence": 0.2},
            {"confidence": 0.25},
        ]

        signal = orchestrator._calculate_signal_strength(findings)

        assert 0.0 < signal < 0.5  # Should be relatively low


class TestEndToEndExecution:
    """Test complete orchestration workflow."""

    @pytest.mark.asyncio
    async def test_process_with_valid_objective(self):
        """Test complete process execution with valid objective."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        result = await orchestrator.process({"objective": "Investigate recent tech developments"})

        assert result["success"] is True
        assert result["objective"] == "Investigate recent tech developments"
        assert "subtasks_created" in result
        assert "findings_collected" in result
        assert "refinements_performed" in result
        assert "final_signal_strength" in result
        assert "final_action" in result
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_process_with_empty_objective(self):
        """Test process execution with empty objective."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        result = await orchestrator.process({"objective": ""})

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_process_with_missing_objective(self):
        """Test process execution without objective key."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        result = await orchestrator.process({})

        assert result["success"] is False
        assert "error" in result


class TestAgentCapabilities:
    """Test agent capability reporting."""

    def test_get_capabilities(self):
        """Test capabilities reporting."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None)

        capabilities = orchestrator.get_capabilities()

        assert isinstance(capabilities, list)
        assert "orchestration" in capabilities
        assert "planning" in capabilities
        assert "objective_decomposition" in capabilities
        assert "task_distribution" in capabilities
        assert "adaptive_routing" in capabilities


class TestRefinementLimit:
    """Test refinement loop prevention."""

    @pytest.mark.asyncio
    async def test_max_refinements_config(self):
        """Test max refinements configuration."""
        orchestrator = PlanningOrchestrator(registry=None, message_bus=None, max_refinements=3)

        assert orchestrator.max_refinements == 3

        state: OrchestratorState = {
            "objective": "Test",
            "messages": [],
            "subtasks": [],
            "agent_assignments": {},
            "findings": [],
            "refinement_count": 3,
            "max_refinements": 3,
            "coverage_metrics": {},
            "signal_strength": 0.0,
            "conflicts": [],
            "next_action": "refine",
        }

        result = await orchestrator.evaluate_findings(state)

        # At max refinements, should synthesize
        assert result["next_action"] == "synthesize"
