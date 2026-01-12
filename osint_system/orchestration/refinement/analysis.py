"""Signal analysis and coverage metrics for investigation refinement."""

from typing import List, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


def calculate_signal_strength(
    findings: List[Dict[str, Any]],
    investigation_keywords: List[str] = None
) -> float:
    """
    Calculate signal strength from findings based on relevance indicators.

    Analyzes findings for:
    - Keyword matches with investigation objective
    - Entity mentions (proper nouns, organizations)
    - Source credibility scores
    - Information density (content length, specificity)

    Args:
        findings: List of finding dictionaries with fields:
            - content: Finding text
            - source: Source identifier
            - confidence: 0.0-1.0 confidence score
            - metadata: Optional dict with keywords, entities, credibility
        investigation_keywords: Optional keywords from objective for relevance scoring

    Returns:
        Signal strength score 0.0-1.0
    """
    if not findings:
        return 0.0

    keyword_set = set(k.lower() for k in investigation_keywords) if investigation_keywords else set()

    # Calculate component scores for each finding
    scores = []
    for finding in findings:
        # Component 1: Keyword relevance (0.3 weight)
        keyword_score = _calculate_keyword_match(finding, keyword_set)

        # Component 2: Entity density (0.2 weight)
        entity_score = _calculate_entity_density(finding)

        # Component 3: Source credibility (0.3 weight)
        credibility_score = _get_credibility_score(finding)

        # Component 4: Information density (0.2 weight)
        density_score = _calculate_information_density(finding)

        # Weighted combination
        finding_score = (
            keyword_score * 0.3 +
            entity_score * 0.2 +
            credibility_score * 0.3 +
            density_score * 0.2
        )

        scores.append(finding_score)

    # Overall signal strength: average of finding scores
    signal_strength = sum(scores) / len(scores) if scores else 0.0

    logger.debug(
        "Signal strength calculated",
        findings_count=len(findings),
        signal_strength=f"{signal_strength:.3f}"
    )

    return min(signal_strength, 1.0)


def _calculate_keyword_match(finding: Dict[str, Any], keywords: Set[str]) -> float:
    """
    Calculate keyword match score for a finding.

    Args:
        finding: Finding dictionary with 'content' field
        keywords: Set of investigation keywords (lowercase)

    Returns:
        Match score 0.0-1.0
    """
    if not keywords:
        return 0.5  # Neutral if no keywords

    content = finding.get("content", "").lower()
    metadata_keywords = finding.get("metadata", {}).get("keywords", [])

    # Combine content words and metadata keywords
    content_words = set(content.split())
    if metadata_keywords:
        content_words.update(k.lower() for k in metadata_keywords)

    # Calculate overlap
    matches = keywords.intersection(content_words)
    match_ratio = len(matches) / len(keywords) if keywords else 0.0

    # Boost for high match rates
    return min(match_ratio * 1.5, 1.0)


def _calculate_entity_density(finding: Dict[str, Any]) -> float:
    """
    Calculate entity density score.

    Higher scores for findings with more proper nouns, organizations, locations.

    Args:
        finding: Finding dictionary with optional 'metadata.entities' field

    Returns:
        Entity density score 0.0-1.0
    """
    metadata = finding.get("metadata", {})
    entities = metadata.get("entities", [])

    if entities:
        # Use explicit entity count from metadata
        entity_count = len(entities)
    else:
        # Fallback: rough heuristic using capitalized words
        content = finding.get("content", "")
        words = content.split()
        entity_count = sum(1 for word in words if word and word[0].isupper() and len(word) > 1)

    # Normalize by content length
    content_length = len(finding.get("content", "").split())
    if content_length == 0:
        return 0.0

    entity_density = entity_count / content_length

    # Scale to 0-1 range (assume 15% entity density is "high")
    return min(entity_density / 0.15, 1.0)


def _get_credibility_score(finding: Dict[str, Any]) -> float:
    """
    Get source credibility score.

    Args:
        finding: Finding dictionary with optional 'metadata.credibility' or 'source' field

    Returns:
        Credibility score 0.0-1.0
    """
    metadata = finding.get("metadata", {})

    # Check for explicit credibility score
    if "credibility" in metadata:
        cred = metadata["credibility"]

        # Handle string credibility levels
        if isinstance(cred, str):
            cred_lower = cred.lower()
            if cred_lower in ["high", "very high", "excellent"]:
                return 0.9
            elif cred_lower in ["medium", "moderate", "good"]:
                return 0.7
            elif cred_lower in ["low", "poor", "questionable"]:
                return 0.4
            else:
                return 0.6  # Default for unknown strings

        # Handle numeric credibility
        return max(0.0, min(1.0, cred))

    # Check for source reputation mapping
    source = finding.get("source", "").lower()

    # Simple heuristic based on source patterns
    if any(term in source for term in ["reuters", "ap", "bbc", "government", "official"]):
        return 0.9
    elif any(term in source for term in ["news", "journal", "times", "post"]):
        return 0.7
    elif any(term in source for term in ["blog", "social", "forum", "reddit"]):
        return 0.5
    elif any(term in source for term in ["unknown", "anonymous"]):
        return 0.3

    # Default: moderate credibility
    return 0.6


def _calculate_information_density(finding: Dict[str, Any]) -> float:
    """
    Calculate information density score.

    Longer, more detailed findings score higher.

    Args:
        finding: Finding dictionary with 'content' field

    Returns:
        Density score 0.0-1.0
    """
    content = finding.get("content", "")
    word_count = len(content.split())

    # Score based on content length
    if word_count < 20:
        return 0.3  # Very brief
    elif word_count < 50:
        return 0.5  # Short
    elif word_count < 150:
        return 0.7  # Medium
    elif word_count < 300:
        return 0.9  # Long
    else:
        return 1.0  # Very detailed


@dataclass
class CoverageMetrics:
    """
    Tracks coverage metrics for investigation completeness.

    Metrics:
        source_diversity: Ratio of unique sources to target sources (0.0-1.0)
        geographic_coverage: Ratio of unique locations to expected locations (0.0-1.0)
        temporal_coverage: Coverage of expected time range (0.0-1.0)
        topic_completeness: Ratio of covered subtopics to total subtopics (0.0-1.0)
    """

    # Target values for coverage
    target_source_count: int = 10
    target_locations: Set[str] = field(default_factory=set)
    expected_subtopics: Set[str] = field(default_factory=set)
    time_range_days: int = 30

    # Observed values
    unique_sources: Set[str] = field(default_factory=set)
    observed_locations: Set[str] = field(default_factory=set)
    covered_subtopics: Set[str] = field(default_factory=set)
    earliest_timestamp: datetime = None
    latest_timestamp: datetime = None

    def update_from_finding(self, finding: Dict[str, Any]):
        """
        Update metrics from a new finding.

        Args:
            finding: Finding dictionary with source, metadata fields
        """
        # Update source diversity
        source = finding.get("source")
        if source:
            self.unique_sources.add(source)

        # Update geographic coverage
        metadata = finding.get("metadata", {})
        locations = metadata.get("locations", [])
        if locations:
            self.observed_locations.update(locations)

        # Update topic coverage
        topics = metadata.get("topics", [])
        if topics:
            self.covered_subtopics.update(topics)

        # Update temporal coverage
        timestamp = finding.get("timestamp")
        if timestamp:
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    timestamp = None

            if timestamp:
                if self.earliest_timestamp is None or timestamp < self.earliest_timestamp:
                    self.earliest_timestamp = timestamp
                if self.latest_timestamp is None or timestamp > self.latest_timestamp:
                    self.latest_timestamp = timestamp

    def get_source_diversity(self) -> float:
        """
        Calculate source diversity metric.

        Returns:
            Ratio of unique sources to target (0.0-1.0)
        """
        if self.target_source_count == 0:
            return 0.0

        return min(len(self.unique_sources) / self.target_source_count, 1.0)

    def get_geographic_coverage(self) -> float:
        """
        Calculate geographic coverage metric.

        Returns:
            Ratio of observed locations to target locations (0.0-1.0)
        """
        if not self.target_locations:
            # If no specific targets, use simple coverage heuristic
            return min(len(self.observed_locations) / 5.0, 1.0)  # Assume 5 locations is "complete"

        # Calculate overlap with target locations
        overlap = len(self.observed_locations.intersection(self.target_locations))
        return overlap / len(self.target_locations)

    def get_temporal_coverage(self) -> float:
        """
        Calculate temporal coverage metric.

        Returns:
            Coverage of expected time range (0.0-1.0)
        """
        if not self.earliest_timestamp or not self.latest_timestamp:
            return 0.0

        # Calculate time range covered
        time_span_days = (self.latest_timestamp - self.earliest_timestamp).total_seconds() / 86400

        if self.time_range_days == 0:
            return 0.0

        return min(time_span_days / self.time_range_days, 1.0)

    def get_topic_completeness(self) -> float:
        """
        Calculate topic completeness metric.

        Returns:
            Ratio of covered subtopics to expected subtopics (0.0-1.0)
        """
        if not self.expected_subtopics:
            # If no specific topics, use simple coverage heuristic
            return min(len(self.covered_subtopics) / 5.0, 1.0)  # Assume 5 topics is "complete"

        # Calculate overlap with expected subtopics
        overlap = len(self.covered_subtopics.intersection(self.expected_subtopics))
        return overlap / len(self.expected_subtopics)

    def get_overall_coverage(self) -> Dict[str, float]:
        """
        Get all coverage metrics.

        Returns:
            Dictionary with all coverage scores (0.0-1.0)
        """
        return {
            "source_diversity": self.get_source_diversity(),
            "geographic_coverage": self.get_geographic_coverage(),
            "temporal_coverage": self.get_temporal_coverage(),
            "topic_completeness": self.get_topic_completeness(),
        }

    def is_coverage_sufficient(self, thresholds: Dict[str, float] = None) -> bool:
        """
        Check if coverage meets minimum thresholds.

        Args:
            thresholds: Dict of metric -> threshold (0.0-1.0)
                       Defaults: source_diversity=0.7, geographic_coverage=0.6,
                                temporal_coverage=0.5, topic_completeness=0.6

        Returns:
            True if all thresholds met
        """
        if thresholds is None:
            thresholds = {
                "source_diversity": 0.7,
                "geographic_coverage": 0.6,
                "temporal_coverage": 0.5,
                "topic_completeness": 0.6,
            }

        coverage = self.get_overall_coverage()

        for metric, threshold in thresholds.items():
            if coverage.get(metric, 0.0) < threshold:
                return False

        return True


def check_diminishing_returns(
    new_findings: List[Dict[str, Any]],
    existing_findings: List[Dict[str, Any]],
    novelty_threshold: float = 0.2
) -> float:
    """
    Check if new findings provide diminishing returns.

    Compares new findings to existing ones to detect redundancy.

    Args:
        new_findings: Recently collected findings
        existing_findings: Previously collected findings
        novelty_threshold: Minimum novelty score to consider returns sufficient (0.0-1.0)

    Returns:
        Novelty score 0.0-1.0 (higher = more novel information)
        Score < novelty_threshold indicates diminishing returns
    """
    if not new_findings:
        return 0.0

    if not existing_findings:
        # All findings are novel if nothing existed before
        return 1.0

    # Calculate novelty based on:
    # 1. New unique sources
    # 2. New unique keywords/entities
    # 3. Content similarity (inverse)

    # Component 1: Source novelty
    existing_sources = {f.get("source") for f in existing_findings if f.get("source")}
    new_sources = {f.get("source") for f in new_findings if f.get("source")}
    new_unique_sources = new_sources - existing_sources

    source_novelty = len(new_unique_sources) / len(new_sources) if new_sources else 0.0

    # Component 2: Entity/keyword novelty
    existing_entities = set()
    for f in existing_findings:
        entities = f.get("metadata", {}).get("entities", [])
        keywords = f.get("metadata", {}).get("keywords", [])
        existing_entities.update(entities)
        existing_entities.update(keywords)

    new_entities = set()
    for f in new_findings:
        entities = f.get("metadata", {}).get("entities", [])
        keywords = f.get("metadata", {}).get("keywords", [])
        new_entities.update(entities)
        new_entities.update(keywords)

    if new_entities:
        new_unique_entities = new_entities - existing_entities
        entity_novelty = len(new_unique_entities) / len(new_entities)
    else:
        entity_novelty = 0.5  # Neutral if no entities

    # Component 3: Content novelty (simplified - in production would use embeddings)
    content_novelty = _calculate_content_novelty(new_findings, existing_findings)

    # Weighted combination
    novelty_score = (
        source_novelty * 0.3 +
        entity_novelty * 0.4 +
        content_novelty * 0.3
    )

    logger.debug(
        "Diminishing returns check",
        novelty_score=f"{novelty_score:.3f}",
        source_novelty=f"{source_novelty:.2f}",
        entity_novelty=f"{entity_novelty:.2f}",
        content_novelty=f"{content_novelty:.2f}",
        diminishing=novelty_score < novelty_threshold
    )

    return min(novelty_score, 1.0)


def _calculate_content_novelty(
    new_findings: List[Dict[str, Any]],
    existing_findings: List[Dict[str, Any]]
) -> float:
    """
    Calculate content-level novelty using simple heuristics.

    In production, this would use embeddings or semantic similarity.

    Args:
        new_findings: New findings to check
        existing_findings: Existing findings corpus

    Returns:
        Content novelty score 0.0-1.0
    """
    # Extract word sets from existing findings
    existing_words = set()
    for finding in existing_findings:
        content = finding.get("content", "").lower()
        existing_words.update(content.split())

    # Calculate new word ratio
    total_new_words = 0
    novel_new_words = 0

    for finding in new_findings:
        content = finding.get("content", "").lower()
        words = content.split()
        total_new_words += len(words)

        for word in words:
            if word not in existing_words and len(word) > 3:  # Ignore short common words
                novel_new_words += 1

    if total_new_words == 0:
        return 0.0

    # Novel word ratio
    novelty_ratio = novel_new_words / total_new_words

    # Scale: 10% new words = 50% novelty, 30% new words = 100% novelty
    scaled_novelty = min(novelty_ratio / 0.3, 1.0)

    return scaled_novelty
