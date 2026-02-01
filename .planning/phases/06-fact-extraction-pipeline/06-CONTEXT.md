# Phase 6: Fact Extraction Pipeline - Context

**Gathered:** 2026-02-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract discrete, verifiable facts from raw text acquired by crawlers and produce structured JSON output. This phase takes crawler output (articles, documents, social posts) and transforms them into structured fact records with full provenance, confidence metrics, and relationship hints.

**In scope:** Fact identification, structured extraction, confidence scoring, source attribution, deduplication logic
**Out of scope:** Fact classification (Phase 7), verification (Phase 8), knowledge graph storage (Phase 9)

</domain>

<design_philosophy>
## Established Design Principle: Detail Over Compactness

**This principle was established during Phase 6 discussion and MUST carry through Phases 6-10.**

In OSINT, collapsing information is losing intelligence. When faced with a tradeoff between compact representation and detailed capture, always choose detail. Downstream agents can ignore fields they don't need; they cannot recover information that was never captured.

**Rationale:**
- The source of information is itself information (who said what matters)
- Multiple sources reporting the same claim is different from one source (corroboration signal)
- Attribution chains reveal reliability patterns
- Decisions made in extraction directly constrain what classification/verification can do

**Application:**
- Separate fields for orthogonal concepts (don't combine into composite scores)
- Preserve original text alongside structured extraction
- Full provenance chains, not just immediate source
- Explicit metadata flags rather than implicit assumptions

</design_philosophy>

<decisions>
## Implementation Decisions

### Fact Granularity

#### Atomicity Level: Single Assertion
**Decision:** Facts are single subject-predicate-object assertions, not maximally decomposed atoms.

**Rationale:** Maximally atomic decomposition ("Putin" + "visited" + "Beijing" + "March 2024" as separate linked claims) creates explosion of records without verification benefit. A single assertion ("Putin visited Beijing in March 2024") is the natural unit for verification — you verify the claim, not its components.

**Downstream impact:** Classification agent receives coherent claims. Verification agent has clear verification targets.

---

#### Entity Extraction: Facts + Key Entities
**Decision:** Extract both verifiable assertions AND notable entities (people, organizations, locations) even when entities appear without assertions.

**Rationale:** Entity mentions without explicit claims still provide intelligence value. "The document mentions FSB, GRU, and SVR" is useful context even without specific claims about those entities. Entity co-occurrence patterns inform analysis.

**Downstream impact:** Knowledge graph (Phase 9) has richer entity data. Analysis agent can detect patterns in entity co-occurrence.

---

#### Temporal Handling: Extract with Uncertainty Flag
**Decision:** Extract all temporal claims with explicit precision metadata: `temporal_precision: 'explicit' | 'inferred' | 'unknown'`

**Rationale:** Discarding facts without explicit dates loses information. Inferring dates silently creates false precision. Flagging uncertainty lets downstream agents decide how to weight temporal information. A fact with `temporal_precision: 'inferred'` (from article date) is still useful but should be treated differently than `temporal_precision: 'explicit'` (stated in text).

**Downstream impact:** Verification agent knows which temporal claims need corroboration. Timeline analysis can weight by precision.

---

#### Negations and Denials: Convert to Positive with Status
**Decision:** Represent denials as the underlying claim with assertion metadata, not as negation flags.

**Example:** "Russia denied involvement" becomes:
```json
{
  "claim": "Russian involvement in X",
  "assertion_type": "denial",
  "asserter": "Russia",
  "source": "..."
}
```

**Rationale:** A `negation: true` flag is ambiguous — does it mean grammatical negation, someone denied it, or evidence refutes it? These are semantically different. The denial itself is intelligence (Russia felt the need to deny). The underlying claim is what needs verification. Separating claim from stance preserves both pieces of information and makes the verification target explicit.

**Downstream impact:** Verification agent knows to verify the underlying claim. Classification agent can reason about who is asserting/denying. Contradiction detection becomes straightforward (same claim, different stances).

---

#### Quoted Speech: Extract as Nested Facts
**Decision:** "Official said X happened" produces two linked facts: the meta-fact about the statement AND the underlying claim marked as reported.

**Rationale:** Both are intelligence. That an official made a statement is verifiable. What the official claimed is separately verifiable. Losing either loses information.

**Downstream impact:** Verification agent can verify both the statement event and the content. Attribution chain is explicit.

---

#### Implicit Facts: Allow Obvious Inferences
**Decision:** Extract facts that are unambiguously implied, not just explicitly stated. "The late President X" implies "X is deceased."

**Rationale:** Requiring only explicit statements misses obvious information. The threshold is "unambiguous" — if context makes the inference certain, extract it with `extraction_type: 'inferred'` flag.

**Downstream impact:** Richer fact set. Inference flag lets classification weight accordingly.

---

#### Numerical Claims: Extract with Precision Flag
**Decision:** Preserve original form AND add precision metadata: `numeric_precision: 'exact' | 'approximate' | 'order_of_magnitude'`

**Example:** "thousands of troops" becomes:
```json
{
  "value_original": "thousands",
  "value_normalized": [1000, 9999],
  "numeric_precision": "order_of_magnitude"
}
```

**Rationale:** Converting "thousands" to a number loses the original hedging. Keeping only the text loses computability. Preserving both with precision flag lets downstream agents decide how to use the information.

---

#### Geographic Normalization: Normalize to Standard
**Decision:** Normalize place names to canonical form (UN/ISO standard), replacing source variants.

**Rationale:** "Kyiv" vs "Kiev" are the same location. For entity linking and deduplication, canonical forms are necessary. Original form is preserved in the source quote field if needed.

**Downstream impact:** Entity clustering works correctly. Knowledge graph has consistent location nodes.

---

#### Predictions and Future Events: Extract as Predictions
**Decision:** Include claims about future events with explicit `claim_type: 'prediction' | 'planned'` marker.

**Rationale:** "Russia plans to..." is OSINT-relevant intelligence even though it's not yet verifiable. Excluding predictions loses forward-looking intelligence. Explicit typing lets downstream agents handle appropriately.

---

#### Entity Aliases: Cluster Without Resolving
**Decision:** Group likely-same entities (Vladimir Putin, Putin, Russian President) but don't force resolution to single canonical ID.

**Rationale:** Premature resolution creates false equivalences. "Russian President" in 2020 vs 2024 might mean different people. Clustering preserves the relationship while allowing downstream disambiguation with more context.

**Downstream impact:** Knowledge graph (Phase 9) receives clusters, not forced resolutions. Entity resolution happens with full context.

---

### Output Structure

#### Top-Level Structure: Hierarchical
**Decision:** Facts nested under entities/topics they relate to, not flat list or source-grouped.

**Rationale:** Hierarchical structure reflects the semantic organization of intelligence. Facts about Putin are grouped; facts about a location are grouped. This aids analysis and reduces cognitive load.

---

#### Source Text References: Both Quote and Offsets
**Decision:** Include exact quoted text span AND character offsets into source document.

**Rationale:** Quotes provide immediate readability. Offsets enable programmatic access to context. Both serve different consumption patterns.

---

#### Schema Strictness: Validated but Lenient
**Decision:** Warn on missing fields but still produce output. Only ID and claim text are hard requirements.

**Rationale:** Failing extraction because one optional field couldn't be populated loses the entire fact. Better to extract what's available and flag gaps.

---

#### Entity Representation: Both with Linking
**Decision:** Entities appear in claim text (with markers) AND as separate structured entity objects with IDs.

**Example:**
```json
{
  "claim_text": "[E1:Putin] visited [E2:Beijing] in March",
  "entities": [
    {"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"},
    {"id": "E2", "text": "Beijing", "type": "LOCATION", "canonical": "Beijing, China"}
  ]
}
```

**Rationale:** Inline markers show entity positions in text. Structured objects enable typed reasoning. Both are needed.

---

#### Fact IDs: UUID + Content Hash for Dedup
**Decision:** UUID for primary storage identity. Content hash as secondary index for exact-match deduplication.

**Rationale (with downstream analysis):**

| Approach | Same claim, same source | Same claim, different sources | Claim A vs ~A |
|----------|------------------------|------------------------------|---------------|
| UUID | Different IDs | Different IDs | Different IDs |
| Content hash | Same ID | Same ID (if text identical) | Different IDs |

Content hashing only catches exact text duplicates. "Putin visited Beijing" and "Russian President visited Beijing" produce different hashes despite semantic equivalence. Semantic clustering requires embedding similarity, not text hashing — that's consolidation logic (Plan 06-03), not ID scheme.

UUIDs guarantee uniqueness with O(1) generation. Content hash catches wire service republishing cheaply. Semantic equivalence is solved at a different layer.

**Downstream impact:** Phase 7/8 receive facts with stable IDs. Deduplication works across sources. Semantic clustering handled separately.

---

#### Relationship Hints: Explicit Relation Types
**Decision:** Extract obvious supports/contradicts/temporal-sequence relationships between facts when evident in text.

**Rationale:** "However, officials disputed this" explicitly signals contradiction. Capturing this at extraction time saves classification work. Only extract when obvious; don't force inference.

**Downstream impact:** Classification agent has head start on contradiction detection.

---

#### Metadata Structure: Nested by Category
**Decision:** Group metadata into sub-objects: `provenance{}`, `extraction{}`, `quality{}`

**Rationale:** Logical grouping aids readability and consumption. Different downstream agents care about different categories.

---

#### Schema Versioning: Explicit Version Field
**Decision:** Include `schema_version` field; breaking changes increment version.

**Rationale:** Schema will evolve. Explicit versioning enables backwards compatibility and migration paths.

---

#### Source Text Inclusion: References Only
**Decision:** Include source ID + offsets. Raw text stored separately in data store.

**Rationale:** Avoids text duplication across facts from same source. Keeps fact records compact while maintaining traceability.

---

### Extraction Confidence

#### Confidence Representation: Separate Fields for Orthogonal Dimensions
**Decision:** Two separate float fields, NOT a composite score:
```python
extraction_confidence: float  # 0.0-1.0 — LLM's parsing accuracy
claim_clarity: float          # 0.0-1.0 — Source text ambiguity
```

**Rationale:** These measure different things:
- **Extraction confidence:** Did the LLM correctly parse this from the text? (process quality)
- **Claim clarity:** Is the source text itself unambiguous? (input quality)

A fact can be:
- High extraction / High clarity: Clear text, correctly parsed
- High extraction / Low clarity: Vague text ("sources suggest..."), but correctly captured as vague
- Low extraction / High clarity: Complex sentence made parsing uncertain, but claim itself is precise

Combining them destroys information Phase 7 needs. "Dubious" classification might stem from unclear source (verification can't fix) vs uncertain extraction (re-extraction might help). Keeping separate lets downstream agents reason appropriately.

**Downstream impact:** Classification can distinguish source-quality issues from extraction-quality issues. Verification knows whether re-extraction or additional sourcing is the right remedy.

---

#### Inclusion Threshold: Configurable, Default Include All
**Decision:** No hard extraction threshold by default. Configurable per-investigation if needed.

**Rationale:** Downstream classification is better positioned to make inclusion decisions with full context. Extraction's job is to extract, not filter.

---

#### Hedged Language: Explicit Penalty to Claim Clarity
**Decision:** Words like "allegedly", "reportedly", "sources say" directly reduce `claim_clarity` score.

**Rationale:** Hedge words are signal that the source text is uncertain. This is claim-level uncertainty, not extraction uncertainty. Reducing clarity score reflects this.

---

#### Explainability: Full Extraction Trace
**Decision:** Include detailed extraction reasoning for debugging/audit, not just scores.

**Example:**
```json
{
  "extraction_confidence": 0.85,
  "claim_clarity": 0.6,
  "extraction_trace": {
    "parsing_notes": "Complex nested clause structure",
    "clarity_factors": ["hedged with 'reportedly'", "anonymous source"],
    "entity_resolution": "Putin resolved via coreference with 'Russian President' in prior sentence"
  }
}
```

**Rationale:** Scores alone don't explain why. For debugging, audit, and improving prompts, full reasoning trace is essential.

---

#### Deduplication: Threshold-Filtered Linking
**Decision:**
1. Identify semantic duplicates (same claim from different sources)
2. Apply low threshold (0.3) — below threshold, discard
3. Above threshold: link as variants, preserve all source provenance

**Rationale:** Source provenance is intelligence. Three wire services reporting the same claim is different from one blog. But very low confidence extractions (below 0.3) add noise without value. Threshold filters noise while preserving source plurality.

**Downstream impact:** Classification sees one canonical claim with N supporting sources. Corroboration signal preserved. Low-quality extractions filtered.

---

### Source Attribution

#### Source Type vs Hop Count: Separate Orthogonal Fields
**Decision:** Track BOTH as separate fields:
```python
hop_count: int                    # Distance from original (0 = eyewitness)
source_type: str                  # Category: 'wire', 'official', 'social', etc.
source_classification: str        # 'primary' | 'secondary' | 'tertiary'
```

**Rationale:** These are not interchangeable representations — they're different dimensions.

A wire service (Reuters) quoting a government official:
- hop_count: 1
- source_type: 'wire_service'
- citing_source_type: 'official_statement'
- source_classification: 'secondary' (journalistic sense)

All three fields carry different information. Collapsing them loses intelligence.

---

#### Attribution Chain Depth: Full Chain
**Decision:** Capture complete provenance: eyewitness → local paper → wire → our document

**Rationale:** Each hop in the chain can introduce distortion. Full chain enables:
- Reliability assessment (how many intermediaries?)
- Pattern detection (which sources cite which?)
- Error tracing (where did misreporting originate?)

---

#### Attribution Phrase Handling: Preserve Verbatim + Parse
**Decision:** Keep original phrase ("according to Reuters citing officials") AND extract structured chain.

**Rationale:** Original phrasing may contain nuance lost in parsing. Structured chain enables computation. Both are needed per detail-over-compactness principle.

---

#### Anonymous Sources: Structured Anonymous Entity
**Decision:** Represent anonymous sources as entities with available metadata:
```json
{
  "entity_type": "anonymous_source",
  "descriptors": {
    "role": "official",
    "affiliation": "US_government",
    "department": "State Department",
    "seniority": "senior"
  },
  "anonymity_granted_by": "source_document_id"
}
```

**Rationale:** "Senior US official" contains information even though identity is unknown. Capturing available descriptors enables pattern analysis (do "senior US officials" tend to be reliable on topic X?).

---

#### Source Reliability History: Cross-Investigation
**Decision:** Maintain persistent source reliability scores across investigations.

**Rationale:** A source's track record is intelligence. If Reuters has been reliable across 50 investigations, that informs credibility weighting. Per-investigation only loses this accumulated knowledge.

**Downstream impact:** Phase 9 Knowledge Graph stores source reliability. New investigations benefit from historical accuracy.

</decisions>

<specifics>
## Specific Ideas

### Downstream Compatibility Concerns
The user explicitly requested that Phase 6 decisions not "lay down a minefield" for Phases 7 and 8. Key forward-compatibility considerations:

1. **Separate confidence dimensions** — Classification needs to distinguish extraction issues from source issues
2. **UUID + content hash** — Enables both stable references and deduplication without semantic conflation
3. **Full provenance chains** — Verification needs to trace claims to original sources
4. **Denial representation** — Verification target is explicit (the underlying claim, not the denial event)

### Schema Example (Illustrative)
```json
{
  "schema_version": "1.0",
  "fact_id": "uuid-here",
  "content_hash": "sha256-here",

  "claim": {
    "text": "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
    "assertion_type": "statement",
    "claim_type": "event"
  },

  "entities": [
    {"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin", "cluster_id": "cluster-123"},
    {"id": "E2", "text": "Beijing", "type": "LOCATION", "canonical": "Beijing, China"}
  ],

  "temporal": {
    "id": "T1",
    "value": "2024-03",
    "precision": "month",
    "temporal_precision": "explicit"
  },

  "provenance": {
    "source_id": "source-uuid",
    "quote": "Russian President Vladimir Putin visited Beijing in March 2024",
    "offsets": {"start": 1542, "end": 1601},
    "attribution_chain": [
      {"entity": "Kremlin spokesperson", "type": "official", "hop": 0},
      {"entity": "TASS", "type": "wire_service", "hop": 1},
      {"entity": "Reuters", "type": "wire_service", "hop": 2}
    ],
    "hop_count": 2,
    "source_type": "wire_service",
    "source_classification": "secondary"
  },

  "quality": {
    "extraction_confidence": 0.92,
    "claim_clarity": 0.88,
    "extraction_trace": {
      "parsing_notes": "Direct statement, clear structure",
      "clarity_factors": [],
      "entity_resolution": "Putin identified from proper noun"
    }
  },

  "extraction": {
    "extracted_at": "2026-02-01T14:30:00Z",
    "model_version": "gemini-1.5-flash",
    "extraction_type": "explicit"
  },

  "relationships": [
    {"type": "supports", "target_fact_id": "uuid-other", "confidence": 0.7}
  ],

  "variants": ["uuid-variant-1", "uuid-variant-2"]
}
```

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 06-fact-extraction-pipeline*
*Context gathered: 2026-02-01*
