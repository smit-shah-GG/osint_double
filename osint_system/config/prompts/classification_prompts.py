"""Prompt templates for fact classification per Phase 7 CONTEXT.md.

LLM-assisted classification for:
- Entity significance assessment (world leaders, officials, etc.)
- Event type categorization (military action, diplomatic, routine)
- Vague attribution pattern detection

The Boolean logic gates for dubious detection are rule-based.
LLM assists with semantic understanding where rules are insufficient.
"""

ENTITY_SIGNIFICANCE_PROMPT = '''Assess the geopolitical significance of entities in this fact.

FACT:
{fact_text}

ENTITIES:
{entities}

Rate each entity's significance for geopolitical analysis:
- world_leader (1.0): Heads of state, prime ministers
- senior_official (0.8): Cabinet members, ambassadors, military commanders
- government_official (0.6): Lower-ranking officials, spokespersons
- company_executive (0.5): CEOs, executives of major companies
- organization (0.4): Named organizations, agencies
- public_figure (0.4): Known individuals without official capacity
- location_major (0.6): Capitals, major cities, strategic locations
- location_minor (0.3): Minor locations

Return JSON:
{{
    "entities": [
        {{"id": "E1", "text": "...", "significance": "world_leader", "score": 1.0}},
        ...
    ],
    "overall_significance": 0.0-1.0
}}'''


EVENT_TYPE_PROMPT = '''Categorize the event type in this fact for geopolitical impact assessment.

FACT:
{fact_text}

CLAIM TYPE: {claim_type}
ASSERTION TYPE: {assertion_type}

Categorize the event:
- military_action (1.0): Combat, troop movements, weapons deployment
- treaty_agreement (0.9): Formal agreements, treaties, accords
- sanctions (0.9): Economic sanctions, embargoes, restrictions
- diplomatic_meeting (0.7): Summits, official visits, negotiations
- policy_announcement (0.6): Policy changes, new regulations
- official_statement (0.5): Press releases, spokesperson comments
- routine_activity (0.2): Regular operations, standard procedures

Return JSON:
{{
    "event_type": "military_action|treaty_agreement|...",
    "score": 0.0-1.0,
    "reasoning": "brief explanation"
}}'''


VAGUE_ATTRIBUTION_PATTERNS = [
    # English vague patterns
    r"sources?\s+(?:say|said|claim|suggest|indicate)",
    r"according\s+to\s+(?:sources?|officials?|reports?)",
    r"reportedly",
    r"allegedly",
    r"it\s+is\s+(?:said|believed|reported|understood)",
    r"(?:some|many|several)\s+(?:say|believe|think)",
    r"(?:anonymous|unnamed)\s+(?:source|official)",
    r"people\s+familiar\s+with",
    r"those\s+close\s+to",
    r"insiders?\s+(?:say|claim)",

    # Hedging language
    r"(?:may|might|could)\s+(?:have|be)",
    r"appears?\s+to",
    r"seems?\s+(?:to|like)",
    r"(?:likely|probably|possibly)",
]


# Impact assessment context patterns
CRITICAL_ENTITY_PATTERNS = [
    # World leaders (regex patterns)
    r"(?:president|prime\s+minister|chancellor|king|queen)\s+\w+",
    r"(?:xi|putin|biden|modi|macron|scholz|sunak)",

    # Organizations
    r"(?:nato|un|eu|g7|g20|brics|asean|opec)",
    r"(?:pentagon|kremlin|white\s+house|downing\s+street)",

    # Military
    r"(?:army|navy|air\s+force|military|troops|soldiers)",
    r"(?:nuclear|missile|weapon|bomb)",
]

CRITICAL_EVENT_KEYWORDS = [
    # Military
    "attack", "strike", "invasion", "war", "conflict", "military",
    "nuclear", "missile", "weapon", "troops", "soldiers", "combat",

    # Diplomatic
    "summit", "treaty", "agreement", "sanction", "embargo",
    "diplomatic", "ambassador", "negotiation",

    # Major events
    "election", "coup", "assassination", "emergency", "crisis",
]


__all__ = [
    "ENTITY_SIGNIFICANCE_PROMPT",
    "EVENT_TYPE_PROMPT",
    "VAGUE_ATTRIBUTION_PATTERNS",
    "CRITICAL_ENTITY_PATTERNS",
    "CRITICAL_EVENT_KEYWORDS",
]
