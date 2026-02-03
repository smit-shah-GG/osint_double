"""Prompt templates for LLM-powered agents.

This package contains carefully engineered prompts for each agent type.
Prompts follow Phase 6 CONTEXT.md design decisions:
- Structured JSON output
- Entity markers in claim text
- Separate confidence dimensions
- Full provenance extraction

Modules:
    fact_extraction_prompts: System and user prompts for fact extraction
"""

from osint_system.config.prompts.fact_extraction_prompts import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_USER_PROMPT,
    FACT_EXTRACTION_CHUNK_PROMPT,
)
from osint_system.config.prompts.classification_prompts import (
    ENTITY_SIGNIFICANCE_PROMPT,
    EVENT_TYPE_PROMPT,
    VAGUE_ATTRIBUTION_PATTERNS,
    CRITICAL_ENTITY_PATTERNS,
    CRITICAL_EVENT_KEYWORDS,
)

__all__ = [
    "FACT_EXTRACTION_SYSTEM_PROMPT",
    "FACT_EXTRACTION_USER_PROMPT",
    "FACT_EXTRACTION_CHUNK_PROMPT",
    "ENTITY_SIGNIFICANCE_PROMPT",
    "EVENT_TYPE_PROMPT",
    "VAGUE_ATTRIBUTION_PATTERNS",
    "CRITICAL_ENTITY_PATTERNS",
    "CRITICAL_EVENT_KEYWORDS",
]
