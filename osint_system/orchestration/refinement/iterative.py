"""Iterative refinement engine for adaptive investigation strategies."""

import json
from typing import Optional, Any
from datetime import datetime
from loguru import logger

from osint_system.orchestration.state_schemas import Finding


class RefinementEngine:
    """
    Engine for iterative refinement of OSINT investigations.

    Analyzes findings, generates follow-up questions, and creates targeted
    subtasks for deeper investigation. Implements reflection mechanisms and
    loop prevention to ensure intelligent, bounded refinement.
    """

    def __init__(self, max_iterations: int = 7):
        """
        Initialize the refinement engine.

        Args:
            max_iterations: Maximum refinement iterations to prevent infinite loops
        """
        self.max_iterations = max_iterations
        self.refinement_history = []
        self.follow_up_questions = []
        self.logger = logger.bind(component="RefinementEngine")

    def refine_approach(
        self,
        objective: str,
        findings: list[dict],
        current_iteration: int,
        coverage_metrics: dict,
        signal_strength: float
    ) -> dict:
        """
        Refine the investigation approach based on current findings.

        Analyzes findings, generates follow-up questions, and creates targeted
        subtasks for areas needing deeper investigation.

        Args:
            objective: Original investigation objective
            findings: Current findings collected
            current_iteration: Current refinement iteration number
            coverage_metrics: Current coverage metrics
            signal_strength: Current signal strength score

        Returns:
            Dictionary with refinement strategy including:
            - new_subtasks: List of new targeted subtasks
            - follow_up_questions: Questions for deeper investigation
            - reasoning: Explanation of refinement decisions
            - should_continue: Whether to continue refining
        """
        self.logger.info(
            "Starting refinement",
            iteration=current_iteration,
            findings_count=len(findings),
            signal=f"{signal_strength:.2f}"
        )

        # Check if we should continue refinement
        should_continue = self.should_continue_refinement(
            current_iteration,
            signal_strength,
            coverage_metrics,
            findings
        )

        if not should_continue:
            return {
                "new_subtasks": [],
                "follow_up_questions": [],
                "reasoning": f"Refinement stopped at iteration {current_iteration}",
                "should_continue": False
            }

        # Reflect on current findings
        reflection = self.reflect_on_findings(findings, objective)

        # Generate follow-up questions based on gaps
        follow_ups = self._generate_follow_up_questions(
            reflection["gaps"],
            reflection["patterns"],
            objective
        )

        # Create targeted subtasks for deeper investigation
        new_subtasks = self._create_targeted_subtasks(
            follow_ups,
            reflection["unexplored_angles"],
            current_iteration
        )

        # Record refinement decision
        refinement_record = {
            "iteration": current_iteration,
            "timestamp": datetime.utcnow().isoformat(),
            "gaps_identified": len(reflection["gaps"]),
            "follow_ups_generated": len(follow_ups),
            "subtasks_created": len(new_subtasks),
            "reasoning": reflection["reasoning"]
        }
        self.refinement_history.append(refinement_record)

        return {
            "new_subtasks": new_subtasks,
            "follow_up_questions": follow_ups,
            "reasoning": reflection["reasoning"],
            "should_continue": True,
            "reflection": reflection
        }

    def reflect_on_findings(self, findings: list[dict], objective: str) -> dict:
        """
        Critically analyze current findings to identify gaps and opportunities.

        Args:
            findings: Current findings collected
            objective: Investigation objective

        Returns:
            Reflection dictionary with gaps, patterns, unexplored angles, and reasoning
        """
        self.logger.debug("Reflecting on findings", count=len(findings))

        gaps = []
        patterns = []
        unexplored_angles = []

        # Analyze findings for patterns
        sources = set()
        topics = set()
        confidences = []

        for finding in findings:
            # Extract metadata
            if isinstance(finding, dict):
                source = finding.get("source", "unknown")
                sources.add(source)

                confidence = finding.get("confidence", 0.5)
                confidences.append(confidence)

                # Extract topics from content (simple keyword extraction)
                content = finding.get("content", "")
                if content:
                    words = content.lower().split()
                    for word in words:
                        if len(word) > 5:  # Simple heuristic for meaningful words
                            topics.add(word)

        # Identify gaps
        if len(sources) < 3:
            gaps.append("Limited source diversity - need more varied sources")

        if confidences and sum(confidences) / len(confidences) < 0.6:
            gaps.append("Low average confidence - need stronger evidence")

        if len(findings) < 5:
            gaps.append("Insufficient findings - need broader investigation")

        # Identify patterns
        if len(sources) > 1:
            patterns.append(f"Information from {len(sources)} distinct sources")

        if topics:
            top_topics = list(topics)[:5]
            patterns.append(f"Key topics emerging: {', '.join(top_topics)}")

        # Suggest unexplored angles
        objective_lower = objective.lower()

        if "timeline" not in objective_lower and "when" in objective_lower:
            unexplored_angles.append("Temporal analysis - construct timeline of events")

        if "location" not in objective_lower and "where" in objective_lower:
            unexplored_angles.append("Geographic analysis - map locations involved")

        if "motivation" not in objective_lower and "why" in objective_lower:
            unexplored_angles.append("Motivation analysis - investigate underlying reasons")

        if len(sources) < 5:
            unexplored_angles.append("Source expansion - investigate additional source types")

        # Generate reasoning
        reasoning_parts = []
        if gaps:
            reasoning_parts.append(f"Identified {len(gaps)} gaps in current investigation")
        if patterns:
            reasoning_parts.append(f"Discovered {len(patterns)} emerging patterns")
        if unexplored_angles:
            reasoning_parts.append(f"Found {len(unexplored_angles)} unexplored investigation angles")

        reasoning = ". ".join(reasoning_parts) if reasoning_parts else "Analysis complete, findings comprehensive"

        return {
            "gaps": gaps,
            "patterns": patterns,
            "unexplored_angles": unexplored_angles,
            "reasoning": reasoning,
            "source_count": len(sources),
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0
        }

    def should_continue_refinement(
        self,
        current_iteration: int,
        signal_strength: float,
        coverage_metrics: dict,
        findings: list[dict]
    ) -> bool:
        """
        Determine if refinement should continue based on multiple factors.

        Args:
            current_iteration: Current iteration number
            signal_strength: Current signal strength
            coverage_metrics: Coverage metrics dictionary
            findings: Current findings

        Returns:
            True if refinement should continue, False otherwise
        """
        # Hard limit check
        if current_iteration >= self.max_iterations:
            self.logger.info(f"Max iterations {self.max_iterations} reached, stopping refinement")
            return False

        # Check signal strength improvement
        if len(self.refinement_history) > 0:
            last_record = self.refinement_history[-1]
            if "signal_strength" in last_record:
                last_signal = last_record["signal_strength"]
                signal_improvement = signal_strength - last_signal

                if signal_improvement < 0.05:
                    self.logger.info("Signal strength not improving significantly, stopping")
                    return False

        # Check coverage improvements
        if coverage_metrics:
            # If we have good coverage across multiple dimensions, maybe stop
            good_coverage_count = sum(
                1 for metric in ["source_diversity", "geographic_coverage", "topical_coverage"]
                if coverage_metrics.get(metric, 0) > 0.7
            )

            if good_coverage_count >= 2:
                self.logger.info("Good coverage achieved across multiple dimensions")
                if current_iteration > 3:
                    return False  # Stop after some iterations with good coverage

        # Check novelty of recent findings
        if len(findings) > 10 and current_iteration > 2:
            # Simple novelty check: are recent findings different from earlier ones?
            early_findings = findings[:5]
            recent_findings = findings[-5:]

            # Compare content similarity (simple approach)
            early_content = set()
            recent_content = set()

            for f in early_findings:
                if isinstance(f, dict) and "content" in f:
                    early_content.add(f["content"][:50])  # First 50 chars as signature

            for f in recent_findings:
                if isinstance(f, dict) and "content" in f:
                    recent_content.add(f["content"][:50])

            if early_content and recent_content:
                overlap = len(early_content & recent_content) / len(early_content | recent_content)
                if overlap > 0.5:
                    self.logger.info("High overlap in findings, low novelty")
                    return False

        # Default: continue if under iteration limit
        return True

    def _generate_follow_up_questions(
        self,
        gaps: list[str],
        patterns: list[str],
        objective: str
    ) -> list[str]:
        """
        Generate specific follow-up questions based on identified gaps and patterns.

        Args:
            gaps: Identified gaps in investigation
            patterns: Emerging patterns discovered
            objective: Original objective

        Returns:
            List of follow-up questions for deeper investigation
        """
        questions = []

        # Questions based on gaps
        for gap in gaps[:3]:  # Limit to top 3 gaps
            if "source diversity" in gap.lower():
                questions.append("What do alternative sources reveal about this topic?")
            elif "confidence" in gap.lower():
                questions.append("Can we find corroborating evidence from authoritative sources?")
            elif "insufficient" in gap.lower():
                questions.append("What additional aspects of the objective remain unexplored?")

        # Questions based on patterns
        for pattern in patterns[:2]:  # Limit to top 2 patterns
            if "sources" in pattern.lower():
                questions.append("Do all sources agree on key facts, or are there contradictions?")
            elif "topics" in pattern.lower():
                questions.append("How do the emerging topics relate to the main objective?")

        # Always include a verification question
        questions.append("Can we verify the most critical findings through independent sources?")

        # Store for later reference
        self.follow_up_questions.extend(questions)

        return questions

    def _create_targeted_subtasks(
        self,
        follow_up_questions: list[str],
        unexplored_angles: list[str],
        iteration: int
    ) -> list[dict]:
        """
        Create specific, targeted subtasks from follow-up questions and angles.

        Args:
            follow_up_questions: Questions to investigate
            unexplored_angles: New angles to explore
            iteration: Current iteration number

        Returns:
            List of new subtask dictionaries
        """
        subtasks = []

        # Convert questions to subtasks
        for i, question in enumerate(follow_up_questions[:3]):  # Limit subtasks
            subtasks.append({
                "id": f"REF-{iteration:02d}-{i+1:02d}",
                "description": f"Investigate: {question}",
                "priority": 8 - i,  # Decreasing priority
                "type": "refinement",
                "suggested_sources": ["news", "documents", "social_media"],
                "status": "pending"
            })

        # Convert unexplored angles to subtasks
        for i, angle in enumerate(unexplored_angles[:2]):  # Limit angles
            subtasks.append({
                "id": f"ANG-{iteration:02d}-{i+1:02d}",
                "description": f"Explore: {angle}",
                "priority": 7 - i,
                "type": "exploration",
                "suggested_sources": ["specialized", "academic", "expert"],
                "status": "pending"
            })

        self.logger.info(f"Created {len(subtasks)} targeted subtasks for refinement")
        return subtasks

    def get_refinement_history(self) -> list[dict]:
        """
        Get the complete refinement history for transparency.

        Returns:
            List of refinement records with decisions and reasoning
        """
        return self.refinement_history

    def get_reasoning_trace(self) -> str:
        """
        Generate a human-readable trace of refinement reasoning.

        Returns:
            Formatted string showing the refinement decision trail
        """
        if not self.refinement_history:
            return "No refinement history available"

        lines = ["=== Refinement History ==="]

        for record in self.refinement_history:
            lines.append(f"\nIteration {record['iteration']} ({record['timestamp']}):")
            lines.append(f"  Gaps found: {record.get('gaps_identified', 0)}")
            lines.append(f"  Follow-ups: {record.get('follow_ups_generated', 0)}")
            lines.append(f"  New tasks: {record.get('subtasks_created', 0)}")
            lines.append(f"  Reasoning: {record.get('reasoning', 'Not recorded')}")

        lines.append("\n=== Follow-up Questions Generated ===")
        for i, question in enumerate(self.follow_up_questions[-5:], 1):  # Last 5 questions
            lines.append(f"  {i}. {question}")

        return "\n".join(lines)