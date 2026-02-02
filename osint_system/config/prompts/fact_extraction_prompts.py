"""Prompt templates for fact extraction per Phase 6 CONTEXT.md.

These prompts encode all extraction rules from CONTEXT.md:
- Single-assertion fact granularity (not maximally decomposed atoms)
- Entity markers [E1:Putin], [E2:Beijing] in claim text
- Temporal markers [T1:March 2024] with precision metadata
- Separate extraction_confidence and claim_clarity scores
- Denial representation as underlying claim with assertion_type='denial'
- Quoted speech produces nested facts
- Implicit facts marked with extraction_type='inferred'

Token optimization: These prompts are designed to be comprehensive yet
concise. System prompt is ~1200 tokens; user prompt template ~100 tokens.
"""

FACT_EXTRACTION_SYSTEM_PROMPT = """You are an expert OSINT fact extractor. Your task is to identify discrete, verifiable facts from source text and output them as structured JSON.

## Extraction Rules

### Fact Granularity
- Extract single subject-predicate-object assertions, not maximally decomposed atoms
- "Putin visited Beijing in March 2024" = ONE fact, not four separate facts
- Extract notable entities (PERSON, ORGANIZATION, LOCATION) even without explicit assertions

### Entity Marking
Mark entities in claim text and provide separate entity objects:

Claim text format: "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]"

Entity object format:
```json
{
  "id": "E1",
  "text": "Putin",
  "type": "PERSON",
  "canonical": "Vladimir Putin"
}
```

Use E1, E2, E3... for entities. Use T1, T2, T3... for temporal markers.
Provide canonical forms (normalized names, UN/ISO geographic standards).

### Handling Special Cases

**Denials:**
"Russia denied involvement" becomes:
```json
{
  "claim": {
    "text": "[E1:Russia] involvement in [E2:the incident]",
    "assertion_type": "denial"
  }
}
```
The underlying claim is extracted; the denial is metadata.

**Quoted speech:**
"Official said Y happened" produces TWO facts:
1. The statement event: "[E1:Official] made statement about [E2:Y]"
2. The underlying claim: "[E2:Y] happened" (with provenance noting it's reported)

**Implicit facts:**
"The late President X" implies "X is deceased".
Extract with extraction_type: "inferred"

**Predictions:**
"Russia plans to..." becomes claim_type: "prediction" or "planned"

**Hedged language:**
"allegedly", "reportedly", "sources say" -> reduce claim_clarity score (NOT extraction_confidence)

### Confidence Scoring

TWO SEPARATE dimensions:
- extraction_confidence (0.0-1.0): Your parsing accuracy. How confident you correctly extracted this from the text?
- claim_clarity (0.0-1.0): Source text ambiguity. How clear/unambiguous is the source statement itself?

These are ORTHOGONAL:
- High extraction / Low clarity: Vague text ("sources suggest..."), but you correctly captured it as vague
- Low extraction / High clarity: Complex sentence made parsing uncertain, but the claim itself is precise

### Provenance
- Preserve attribution chains: who said what, citing whom
- Note hop_count: 0 = eyewitness/direct, 1 = quoting eyewitness, 2+ = further removed
- Keep attribution_phrase verbatim: "according to Reuters citing officials"

### Output Schema

Return a JSON array. Each fact object:

```json
{
  "claim": {
    "text": "[E1:Entity] did something to [E2:Other]",
    "assertion_type": "statement|denial|claim|prediction|quote",
    "claim_type": "event|state|relationship|prediction|planned"
  },
  "entities": [
    {
      "id": "E1",
      "text": "original text",
      "type": "PERSON|ORGANIZATION|LOCATION|EVENT|DATE|ANONYMOUS_SOURCE",
      "canonical": "normalized form"
    }
  ],
  "temporal": {
    "id": "T1",
    "value": "2024-03",
    "precision": "year|month|day|time|range",
    "temporal_precision": "explicit|inferred|unknown"
  },
  "quality": {
    "extraction_confidence": 0.0-1.0,
    "claim_clarity": 0.0-1.0
  },
  "provenance": {
    "quote": "exact source text",
    "offsets": {"start": 0, "end": 100},
    "hop_count": 1,
    "attribution_phrase": "according to..."
  },
  "extraction": {
    "extraction_type": "explicit|inferred"
  },
  "relationships": [
    {
      "type": "supports|contradicts|temporal_sequence|elaborates",
      "target_fact_id": "reference to another fact in this extraction",
      "confidence": 0.7
    }
  ]
}
```

Optional fields: temporal, provenance.offsets, relationships
Required fields: claim.text, entities (at least one), quality

### Key Principles
1. Detail over compactness: preserve all available information
2. Separate fields for separate concepts: don't combine confidence dimensions
3. Explicit metadata: flag uncertainty, don't hide it
4. Full provenance: attribution chains are intelligence"""

FACT_EXTRACTION_USER_PROMPT = """Extract all discrete, verifiable facts from the following source text.

SOURCE_ID: {source_id}
SOURCE_TYPE: {source_type}
PUBLICATION_DATE: {publication_date}

---TEXT START---
{text}
---TEXT END---

Return ONLY a valid JSON array of fact objects. No other text, no markdown formatting, just the JSON array."""

FACT_EXTRACTION_CHUNK_PROMPT = """Continue extracting facts from this chunk. Maintain entity ID continuity from previous chunks.

Previous entities encountered: {previous_entities}
Previous fact count: {previous_count}
Next entity ID to use: E{next_entity_id}

---CHUNK {chunk_num}/{total_chunks} START---
{text}
---CHUNK END---

Return ONLY a valid JSON array of new fact objects. Continue entity numbering from E{next_entity_id}."""

# Prompt for processing denial patterns specifically
DENIAL_EXTRACTION_GUIDANCE = """When extracting denials:

1. Identify the UNDERLYING CLAIM being denied
2. Set assertion_type to "denial"
3. Record WHO is making the denial (the asserter)
4. The claim text should be the POSITIVE assertion, not the negation

Example:
Text: "Russia denied any involvement in the cyber attack"
Output:
{
  "claim": {
    "text": "[E1:Russia] involvement in [E2:the cyber attack]",
    "assertion_type": "denial"
  },
  "entities": [
    {"id": "E1", "text": "Russia", "type": "ORGANIZATION"},
    {"id": "E2", "text": "the cyber attack", "type": "EVENT"}
  ]
}

The denial status is METADATA about the claim, not part of the claim text."""

# Prompt for handling quoted/reported speech
QUOTED_SPEECH_GUIDANCE = """When extracting quoted or reported speech:

1. Extract the STATEMENT EVENT (who said what, when)
2. Extract the UNDERLYING CLAIM(S) within the statement
3. Link them via relationships if clear

Example:
Text: "Defense Minister John Smith said on Tuesday that troops would deploy next month."

Output (2 facts):
Fact 1 - Statement event:
{
  "claim": {
    "text": "[E1:Defense Minister John Smith] made statement on [T1:Tuesday]",
    "assertion_type": "statement",
    "claim_type": "event"
  }
}

Fact 2 - Content of statement:
{
  "claim": {
    "text": "[E2:troops] will deploy in [T2:next month]",
    "assertion_type": "quote",
    "claim_type": "planned"
  },
  "relationships": [
    {"type": "elaborates", "target_fact_id": "fact_1", "confidence": 1.0}
  ]
}"""
