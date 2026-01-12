"""Integration tests for Planning & Orchestration Agent with refinement and hierarchical support."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from osint_system.agents.planning_agent import PlanningOrchestrator
from osint_system.orchestration.refinement.iterative import RefinementEngine
from osint_system.orchestration.refinement.hierarchical import (
    SubCoordinator,
    SubCoordinatorFactory,
    combine_sub_coordinator_results
)


class TestPlanningOrchestration:
    """Test suite for planning and orchestration functionality."""

    @pytest.fixture
    def orchestrator(self):
        """Create a PlanningOrchestrator instance for testing."""
        return PlanningOrchestrator(max_refinements=3)

    @pytest.fixture
    def mock_findings(self):
        """Create mock findings for testing."""
        return [
            {
                "source": "news",
                "content": "Breaking: Major event occurred in location X",
                "agent_id": "news_crawler",
                "confidence": 0.8,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"type": "news", "credibility": "high"}
            },
            {
                "source": "social_media",
                "content": "Witness reports from location X confirm event",
                "agent_id": "social_crawler",
                "confidence": 0.6,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"type": "social", "platform": "twitter"}
            },
            {
                "source": "documents",
                "content": "Official report contradicts timeline",
                "agent_id": "doc_crawler",
                "confidence": 0.7,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"type": "document", "classification": "public"}
            }
        ]

    @pytest.mark.asyncio
    async def test_full_refinement_loop(self, orchestrator, mock_findings):
        """Test complete refinement loop with mocked agents."""
        # Create initial state
        state = {
            "objective": "Investigate event at location X",
            "findings": mock_findings[:2],  # Start with 2 findings
            "refinement_count": 0,
            "coverage_metrics": {
                "source_diversity": 0.4,
                "geographic_coverage": 0.3,
                "topical_coverage": 0.5
            },
            "signal_strength": 0.5
        }

        # Execute refinement
        refined_state = await orchestrator.refine_approach(state)

        # Verify refinement occurred
        assert refined_state["refinement_count"] == 1
        assert "refinement_history" in refined_state
        assert len(refined_state["refinement_history"]) > 0

        # Check that new subtasks were created
        assert "subtasks" in refined_state
        # Should have created some refinement subtasks
        refinement_tasks = [
            t for t in refined_state["subtasks"]
            if t.get("type") == "refinement"
        ]
        assert len(refinement_tasks) > 0

        # Verify reasoning was recorded
        history = refined_state["refinement_history"][0]
        assert "reasoning" in history
        assert "follow_ups" in history

    @pytest.mark.asyncio
    async def test_max_refinement_limit(self, orchestrator):
        """Test that refinement stops at max iterations."""
        # Set up state at max refinements
        state = {
            "objective": "Test objective",
            "findings": [],
            "refinement_count": orchestrator.max_refinements,
            "coverage_metrics": {},
            "signal_strength": 0.3,
            "max_refinements": orchestrator.max_refinements
        }

        # Evaluate should decide to synthesize due to limit
        evaluated_state = await orchestrator.evaluate_findings(state)

        assert evaluated_state["next_action"] == "synthesize"
        assert "Max refinements" in evaluated_state["messages"][-1]

    @pytest.mark.asyncio
    async def test_hierarchical_delegation(self):
        """Test hierarchical delegation with sub-coordinators."""
        # Create sub-coordinators for different source types
        sub_coordinators = SubCoordinatorFactory.create_parallel_coordinators(
            objective="Investigate complex event",
            aspects=["news coverage", "social media reaction", "official documents"],
            available_agents=["news_agent", "social_agent", "doc_agent"]
        )

        assert len(sub_coordinators) == 3
        assert "news coverage" in sub_coordinators
        assert "social media reaction" in sub_coordinators

        # Test sub-coordinator execution
        news_coordinator = sub_coordinators["news coverage"]
        assert news_coordinator.source_type == "news"

        # Execute with mock tasks
        mock_tasks = [
            {"id": "T-001", "description": "Find news articles"},
            {"id": "T-002", "description": "Verify sources"}
        ]

        result = await news_coordinator.execute(mock_tasks)

        assert "findings" in result
        assert result["source_type"] == "news"
        assert result["findings_count"] >= 0

    @pytest.mark.asyncio
    async def test_result_aggregation(self, mock_findings):
        """Test aggregation of results from multiple sub-coordinators."""
        # Create mock results from sub-coordinators
        sub_results = [
            {
                "sub_coordinator_id": "SUB-NEWS-001",
                "source_type": "news",
                "findings": [mock_findings[0]],
                "agents_involved": ["news_agent"],
                "findings_count": 1
            },
            {
                "sub_coordinator_id": "SUB-SOCIAL-002",
                "source_type": "social",
                "findings": [mock_findings[1]],
                "agents_involved": ["social_agent"],
                "findings_count": 1
            }
        ]

        # Combine results
        combined = combine_sub_coordinator_results(sub_results)

        assert combined["total_findings"] == 2
        assert len(combined["sub_coordinators"]) == 2
        assert "news" in combined["findings_by_source"]
        assert "social" in combined["findings_by_source"]
        assert len(combined["all_findings"]) == 2

    def test_conflict_detection_and_tracking(self, orchestrator):
        """Test conflict detection and tracking without resolution."""
        # Track a conflict
        conflict = {
            "topic": "Event timeline",
            "version_a": "Event occurred at 10:00 AM",
            "source_a": "news_source_1",
            "version_b": "Event occurred at 11:30 AM",
            "source_b": "official_report"
        }

        orchestrator.track_conflict(conflict)

        # Verify conflict was tracked
        conflicts = orchestrator.get_conflict_report()
        assert len(conflicts) == 1
        assert conflicts[0]["topic"] == "Event timeline"
        assert conflicts[0]["status"] == "unresolved"

        # Track another conflict
        conflict2 = {
            "topic": "Number of participants",
            "version_a": "100 people involved",
            "source_a": "social_media",
            "version_b": "50 people involved",
            "source_b": "police_report"
        }

        orchestrator.track_conflict(conflict2)

        # Verify both conflicts are tracked
        conflicts = orchestrator.get_conflict_report()
        assert len(conflicts) == 2

    @pytest.mark.asyncio
    async def test_diminishing_returns_detection(self, orchestrator, mock_findings):
        """Test that diminishing returns are properly detected."""
        # Create state with repeated similar findings
        similar_findings = [mock_findings[0]] * 5  # Same finding repeated

        state = {
            "objective": "Test objective",
            "findings": similar_findings,
            "refinement_count": 3,
            "coverage_metrics": {
                "source_diversity": 0.8,
                "geographic_coverage": 0.8
            },
            "signal_strength": 0.8,
            "max_refinements": 7
        }

        # Store previous findings for comparison
        orchestrator.previous_findings = similar_findings[:3]

        # Evaluate should detect diminishing returns
        evaluated_state = await orchestrator.evaluate_findings(state)

        # Should decide to synthesize due to diminishing returns
        assert evaluated_state["next_action"] == "synthesize"

    def test_transparency_features(self, orchestrator):
        """Test transparency and reasoning trace features."""
        # Track some conflicts
        orchestrator.track_conflict({
            "topic": "Test conflict",
            "version_a": "Version 1",
            "source_a": "Source A",
            "version_b": "Version 2",
            "source_b": "Source B"
        })

        # Get reasoning trace
        trace = orchestrator.get_reasoning_trace()

        assert "Complete Reasoning Trace" in trace
        assert "Unresolved Conflicts" in trace
        assert "Test conflict" in trace
        assert "Routing Configuration" in trace

        # Test describe method
        description = orchestrator.describe()

        assert "Planning Orchestrator" in description
        assert "LangGraph StateGraph" in description
        assert "Iterative refinement" in description
        assert "Hierarchical sub-coordinator" in description
        assert "conflicts tracked" in description

    @pytest.mark.asyncio
    async def test_complete_orchestration_flow(self, orchestrator):
        """Test complete orchestration flow from objective to synthesis."""
        objective = "Investigate the impact of recent policy changes"

        # Mock Gemini client to avoid API calls
        with patch.object(orchestrator, 'gemini_client') as mock_gemini:
            # Mock decomposition response
            mock_model = Mock()
            mock_response = Mock()
            mock_response.text = """[
                {
                    "id": "ST-001",
                    "description": "Analyze policy document changes",
                    "priority": 9,
                    "suggested_sources": ["documents", "news"]
                },
                {
                    "id": "ST-002",
                    "description": "Track public response",
                    "priority": 7,
                    "suggested_sources": ["social_media", "news"]
                }
            ]"""
            mock_model.generate_content.return_value = mock_response
            mock_gemini.GenerativeModel.return_value = mock_model

            # Execute orchestration
            result = await orchestrator.process({"objective": objective})

            assert result["success"] is True
            assert result["objective"] == objective
            assert result["subtasks_created"] >= 0
            assert "messages" in result

    def test_stopping_conditions(self):
        """Test various stopping conditions for refinement."""
        engine = RefinementEngine(max_iterations=5)

        # Test max iterations stopping
        should_continue = engine.should_continue_refinement(
            current_iteration=5,
            signal_strength=0.5,
            coverage_metrics={},
            findings=[]
        )
        assert should_continue is False

        # Test good coverage stopping
        should_continue = engine.should_continue_refinement(
            current_iteration=4,
            signal_strength=0.8,
            coverage_metrics={
                "source_diversity": 0.8,
                "geographic_coverage": 0.8,
                "topical_coverage": 0.7
            },
            findings=[{} for _ in range(10)]
        )
        assert should_continue is False

    @pytest.mark.asyncio
    async def test_adaptive_routing_logic(self, orchestrator, mock_findings):
        """Test adaptive routing decisions based on different conditions."""
        # Test 1: Strong signal, incomplete coverage -> refine
        state1 = {
            "objective": "Test",
            "findings": mock_findings,
            "refinement_count": 1,
            "coverage_metrics": {"source_diversity": 0.3},
            "signal_strength": 0.8,
            "max_refinements": 7
        }
        result1 = await orchestrator.evaluate_findings(state1)
        assert result1["next_action"] in ["refine", "synthesize"]

        # Test 2: Good coverage -> synthesize
        state2 = {
            "objective": "Test",
            "findings": mock_findings * 3,
            "refinement_count": 2,
            "coverage_metrics": {
                "source_diversity": 0.8,
                "geographic_coverage": 0.7
            },
            "signal_strength": 0.6,
            "max_refinements": 7
        }
        result2 = await orchestrator.evaluate_findings(state2)
        assert result2["next_action"] == "synthesize"


class TestRefinementEngine:
    """Test suite for the RefinementEngine."""

    def test_reflection_on_findings(self):
        """Test reflection mechanism identifies gaps and patterns."""
        engine = RefinementEngine()

        findings = [
            {"source": "news", "content": "Event at location", "confidence": 0.8},
            {"source": "social", "content": "Witness reports", "confidence": 0.5},
        ]

        reflection = engine.reflect_on_findings(findings, "Investigate event")

        assert "gaps" in reflection
        assert "patterns" in reflection
        assert "unexplored_angles" in reflection
        assert "reasoning" in reflection

        # Should identify limited source diversity
        gap_texts = " ".join(reflection["gaps"])
        assert "source" in gap_texts.lower() or "insufficient" in gap_texts.lower()

    def test_follow_up_question_generation(self):
        """Test follow-up question generation based on gaps."""
        engine = RefinementEngine()

        gaps = ["Limited source diversity", "Low confidence evidence"]
        patterns = ["Multiple sources agree on location"]

        questions = engine._generate_follow_up_questions(
            gaps, patterns, "Investigate event"
        )

        assert len(questions) > 0
        assert any("source" in q.lower() for q in questions)
        assert any("verify" in q.lower() for q in questions)

    def test_targeted_subtask_creation(self):
        """Test creation of targeted subtasks from questions."""
        engine = RefinementEngine()

        questions = [
            "Can we verify through official sources?",
            "What do alternative sources reveal?"
        ]
        angles = ["Timeline analysis needed"]

        subtasks = engine._create_targeted_subtasks(questions, angles, iteration=2)

        assert len(subtasks) > 0
        assert all("id" in task for task in subtasks)
        assert all("description" in task for task in subtasks)
        assert all("priority" in task for task in subtasks)

        # Check ID format
        assert any(task["id"].startswith("REF-02") for task in subtasks)
        assert any(task["id"].startswith("ANG-02") for task in subtasks)