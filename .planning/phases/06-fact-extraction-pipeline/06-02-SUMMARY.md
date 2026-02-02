---
phase: 06-fact-extraction-pipeline
plan: 02
subsystem: agents/sifters
tags: [fact-extraction, gemini, llm, prompts, pydantic]

# Dependency graph
requires:
  - phase: 06-01
    provides: ExtractedFact, Entity, Provenance schemas
provides:
  - BaseSifter abstract base class for all sifter agents
  - FactExtractionAgent with Gemini-powered extraction
  - Prompt templates for fact extraction
  - 40 comprehensive agent tests
affects: [06-03, 06-04, 07-classification, 08-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Lazy-load Gemini client to avoid initialization on import
    - Chunk-based extraction for long documents with entity ID continuity
    - Entity type normalization mapping (ORG->ORGANIZATION, LOC->LOCATION)
    - JSON extraction regex handles markdown blocks and surrounding text

key-files:
  created:
    - osint_system/config/prompts/__init__.py
    - osint_system/config/prompts/fact_extraction_prompts.py
    - tests/agents/sifters/__init__.py
    - tests/agents/sifters/test_fact_extraction_agent.py
  modified:
    - osint_system/agents/sifters/base_sifter.py
    - osint_system/agents/sifters/fact_extraction_agent.py
    - osint_system/agents/sifters/__init__.py

key-decisions:
  - "Entity markers in claim text: [E1:name], [T1:date]"
  - "Separate extraction_confidence and claim_clarity per CONTEXT.md"
  - "Denials produce underlying claim with assertion_type='denial'"
  - "Default min_confidence=0.0 (include all facts, let downstream filter)"
  - "Chunk size 12000 chars to leave room for prompt tokens"
  - "Paragraph-boundary splitting for semantic coherence"

patterns-established:
  - "BaseSifter.sift() abstract method for all analytical agents"
  - "Lazy Gemini client initialization via property accessor"
  - "Entity type normalization: ORG/LOC/PER/GPE -> standard EntityType enum"
  - "Mock Gemini pattern: inject mock_genai to agent constructor"

# Metrics
duration: 5min
completed: 2026-02-03
---

# Phase 6 Plan 2: FactExtractionAgent Summary

**BaseSifter base class and FactExtractionAgent with Gemini integration producing ExtractedFact-conformant output with entity markers, separate confidence dimensions, and denial handling per CONTEXT.md**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-02T18:54:16Z
- **Completed:** 2026-02-02T18:59:42Z
- **Tasks:** 3 (Task 2 split into 2a/2b/2c subtasks)
- **Files modified:** 7

## Accomplishments

- BaseSifter abstract base class providing sift()/process() contract for all sifter agents
- FactExtractionAgent with Gemini-powered structured fact extraction
- Comprehensive prompt templates encoding all CONTEXT.md extraction rules
- Chunk-based processing for long documents with entity ID continuity
- Entity type normalization handling common NER variations (ORG, LOC, PER, GPE)
- 40 comprehensive tests with mocked Gemini responses

## Task Commits

Each task was committed atomically:

1. **Task 1: BaseSifter and prompts** - `5db0c86` (feat)
   - base_sifter.py, prompts/__init__.py, fact_extraction_prompts.py
2. **Task 2: FactExtractionAgent** - `82b8b61` (feat)
   - fact_extraction_agent.py, sifters/__init__.py
3. **Task 3: Agent tests** - `ebb1102` (test)
   - test_fact_extraction_agent.py

## Files Created/Modified

- `osint_system/agents/sifters/base_sifter.py` - Abstract base with sift()/process() contract (113 lines)
- `osint_system/agents/sifters/fact_extraction_agent.py` - Complete agent implementation (615 lines)
- `osint_system/agents/sifters/__init__.py` - Package exports BaseSifter, FactExtractionAgent
- `osint_system/config/prompts/__init__.py` - Prompt package init
- `osint_system/config/prompts/fact_extraction_prompts.py` - System/user/chunk prompts (222 lines)
- `tests/agents/sifters/__init__.py` - Test package marker
- `tests/agents/sifters/test_fact_extraction_agent.py` - 40 comprehensive tests (641 lines)

## Key Implementation Details

### Prompt Engineering
System prompt encodes all CONTEXT.md rules:
- Single-assertion fact granularity
- Entity markers [E1:Putin] in claim text
- Temporal markers [T1:March 2024] with precision
- Separate extraction_confidence and claim_clarity
- Denial handling: underlying claim with assertion_type='denial'
- Quoted speech produces nested facts

### Chunking Strategy
- Default chunk size: 12000 chars (leaves room for ~4000 token prompt)
- Splits on paragraph boundaries for semantic coherence
- Falls back to sentence boundaries for large paragraphs
- Maintains entity ID continuity across chunks (E1, E2... continues)

### Entity Type Normalization
```python
type_mapping = {
    "ORG": "ORGANIZATION",
    "LOC": "LOCATION",
    "PER": "PERSON",
    "GPE": "LOCATION",  # Geo-political entity
}
```

## Decisions Made

All decisions followed CONTEXT.md specifications:

1. **Entity markers in claim text** - [E1:Putin] format enables both inline position and structured entity lookup
2. **Separate confidence dimensions** - extraction_confidence (LLM accuracy) and claim_clarity (source ambiguity) are orthogonal per CONTEXT.md
3. **Denial representation** - "Russia denied X" becomes claim X with assertion_type="denial"
4. **Default include all** - min_confidence=0.0 by default; downstream Classification agent makes filtering decisions
5. **Lazy Gemini initialization** - Avoids API key requirement at import time for testing

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - Gemini API key already configured from previous phases.

## Next Phase Readiness

FactExtractionAgent ready for integration:
```python
from osint_system.agents.sifters import FactExtractionAgent

agent = FactExtractionAgent()
results = await agent.sift({
    "text": "Article content...",
    "source_id": "article-001",
    "source_type": "news_outlet",
    "publication_date": "2024-03-15"
})
# Returns: list[dict] of ExtractedFact objects
```

Ready for:
- 06-03: FactStore and FactConsolidator for dedup/storage
- 06-04: ExtractionPipeline bridging crawler output to extraction

---
*Phase: 06-fact-extraction-pipeline*
*Completed: 2026-02-03*
