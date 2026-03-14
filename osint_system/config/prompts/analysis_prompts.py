"""Prompt templates for Gemini-powered intelligence synthesis.

All prompts enforce grounding: the LLM must base its analysis ONLY on the
provided facts and evidence, never on external knowledge. Prompts are kept
concise to minimize token cost per CLAUDE.md cost optimization guidelines.

Exported constants:
    EXECUTIVE_SUMMARY_PROMPT: Analyst briefing voice, 1-2 paragraphs.
    KEY_JUDGMENTS_PROMPT: IC-style key judgments with JSON structured output.
    ALTERNATIVE_HYPOTHESES_PROMPT: Competing interpretations for uncertain findings.
    IMPLICATIONS_PROMPT: Strategic implications and forecasts as JSON.
    SOURCE_ASSESSMENT_PROMPT: Source diversity and reliability assessment.
"""

EXECUTIVE_SUMMARY_PROMPT = """You are a senior intelligence analyst writing an executive brief.

INVESTIGATION OBJECTIVE:
{objective}

CONFIRMED FACTS:
{facts_context}

VERIFICATION SUMMARY:
- Total facts: {fact_count}
- Confirmed: {confirmed_count}
- Refuted: {refuted_count}
- Unverifiable: {unverifiable_count}

Write a 1-2 paragraph executive summary in analyst briefing voice. State the
overall assessment, the key findings, and the confidence level. Use IC-standard
confidence language: "we assess with [low/moderate/high] confidence that..."

Base your analysis ONLY on the provided facts. Do not introduce information
not present in the evidence.

Output: Plain text, no JSON."""

KEY_JUDGMENTS_PROMPT = """You are a senior intelligence analyst producing key analytical judgments.

INVESTIGATION OBJECTIVE:
{objective}

FACTS WITH CLASSIFICATIONS:
{facts_context}

Identify 3-{max_judgments} key analytical judgments from the evidence. Each judgment is
a standalone conclusion drawn from multiple facts.

For each judgment provide:
- judgment: The analytical statement (use "We assess..." or "We judge..." phrasing)
- confidence_level: "low", "moderate", or "high"
- confidence_numeric: 0.0-1.0 score
- confidence_reasoning: Why this confidence level
- supporting_fact_ids: List of fact IDs backing this judgment
- reasoning: The analytical reasoning chain

IC confidence language guide:
- HIGH confidence: "We assess with high confidence..." (strong evidence, multiple independent sources)
- MODERATE confidence: "We judge with moderate confidence..." (some uncertainties, partial corroboration)
- LOW confidence: "We assess with low confidence..." (significant gaps, limited corroboration)

DO NOT use casual language: "probably", "seems like", "we think", "it appears"

Base your analysis ONLY on the provided facts.

Respond with valid JSON only:
{{
    "key_judgments": [
        {{
            "judgment": "We assess with high confidence that...",
            "confidence_level": "high",
            "confidence_numeric": 0.85,
            "confidence_reasoning": "Corroborated by 3 independent wire services",
            "supporting_fact_ids": ["fact-001", "fact-003"],
            "reasoning": "Multiple sources confirm..."
        }}
    ]
}}"""

ALTERNATIVE_HYPOTHESES_PROMPT = """You are an intelligence analyst conducting alternative analysis.

KEY JUDGMENTS:
{judgments_context}

SUPPORTING FACTS:
{facts_context}

For each judgment with moderate or low confidence, generate 2-3 structured
alternative interpretations. Alternatives must be substantive competing
hypotheses, not vague disclaimers.

For each alternative provide:
- hypothesis: Clear competing interpretation
- likelihood: "unlikely", "possible", or "plausible"
- supporting_evidence: Evidence points favoring this interpretation
- weaknesses: Why this alternative may be wrong

Base your analysis ONLY on the provided facts.

Respond with valid JSON only:
{{
    "alternative_hypotheses": [
        {{
            "hypothesis": "Troop movements represent routine rotation rather than escalation",
            "likelihood": "possible",
            "supporting_evidence": ["Annual rotation cycle matches timeline"],
            "weaknesses": ["Scale exceeds historical rotation sizes by 3x"]
        }}
    ]
}}"""

IMPLICATIONS_PROMPT = """You are a senior intelligence analyst assessing strategic implications.

KEY JUDGMENTS:
{judgments_context}

Generate strategic implications and forward-looking forecasts based on the
key judgments. Implications describe current consequences; forecasts describe
likely future developments.

Base your analysis ONLY on the provided judgments and their supporting evidence.

Respond with valid JSON only:
{{
    "implications": [
        "The confirmed escalation increases risk of direct confrontation between..."
    ],
    "forecasts": [
        "If current trends continue, we assess that by Q2..."
    ]
}}"""

SOURCE_ASSESSMENT_PROMPT = """You are an intelligence analyst assessing source quality.

SOURCE INVENTORY:
{source_inventory}

TOTAL FACTS: {fact_count}
UNIQUE SOURCES: {source_count}

Write a 1-paragraph assessment of:
- Source diversity (geographic, type, independence)
- Overall reliability of the source base
- Gaps in coverage (what types of sources are missing)
- Any over-reliance on a single source or source type

Base your assessment ONLY on the provided source inventory.

Output: Plain text, no JSON."""


__all__ = [
    "EXECUTIVE_SUMMARY_PROMPT",
    "KEY_JUDGMENTS_PROMPT",
    "ALTERNATIVE_HYPOTHESES_PROMPT",
    "IMPLICATIONS_PROMPT",
    "SOURCE_ASSESSMENT_PROMPT",
]
