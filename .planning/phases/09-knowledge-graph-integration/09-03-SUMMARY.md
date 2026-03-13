# Phase 9 Plan 03: Fact-to-Graph Mapping & Relationship Extraction Summary

**One-liner:** FactMapper converts ExtractedFact/VerificationResult/FactClassification into GraphNode/GraphEdge with entity resolution; RelationshipExtractor derives 8+ rule-based edge types plus config-gated LLM extraction for CAUSES/PRECEDES/ATTRIBUTED_TO.

---

phase: 09-knowledge-graph-integration
plan: 03
subsystem: agents-sifters-graph
tags: [graph-mapping, entity-resolution, relationship-extraction, rule-based, llm-gated]

requires:
  - Phase 6 (ExtractedFact, Entity, Provenance schemas)
  - Phase 7 (FactClassification, DubiousFlag, ImpactTier)
  - Phase 8 (VerificationResult, VerificationStatus, EvidenceItem)
  - 09-01 (GraphNode, GraphEdge, EdgeType, compute_edge_weight, GraphConfig)

provides:
  - FactMapper for fact-to-graph node/edge transformation
  - Entity resolution with canonical dedup and alias tracking
  - RelationshipExtractor with hybrid rule-based + LLM extraction
  - Cross-investigation entity detection (exact canonical match)

affects:
  - 09-04 (GraphIngestor will use FactMapper + RelationshipExtractor)
  - Phase 10 (Analysis consumes graph nodes/edges produced by these components)

tech-stack:
  added: [] (no new dependencies -- uses structlog, Pydantic, existing schemas)
  patterns:
    - Session-scoped entity resolution via canonical name mapping
    - Hybrid rule-based + LLM extraction with config gate
    - Graceful degradation on LLM failure
    - Static edge deduplication by (source, target, type) key

key-files:
  created:
    - osint_system/agents/sifters/graph/__init__.py
    - osint_system/agents/sifters/graph/fact_mapper.py
    - osint_system/agents/sifters/graph/relationship_extractor.py
    - tests/agents/sifters/graph/__init__.py
    - tests/agents/sifters/graph/test_fact_mapper.py
    - tests/agents/sifters/graph/test_relationship_extractor.py
  modified: []

decisions:
  - id: entity-resolution-exact-match
    decision: "Entity resolution uses exact canonical name match (resolution_confidence=1.0)"
    rationale: "Per RESEARCH.md open question 3: start with exact match, defer fuzzy to Phase 10"
  - id: cross-investigation-dict-interface
    decision: "extract_cross_investigation takes dict[str, list[str]] instead of GraphAdapter"
    rationale: "Decouples from adapter, enables easy testing, adapter query wraps this in practice"
  - id: llm-lower-weight
    decision: "LLM-inferred edges use base weight 0.4 (vs 0.5+ for rule-based)"
    rationale: "LLM inferences are less certain than metadata-derived edges"
  - id: source-node-dedup
    decision: "Source nodes deduplicated by source_id within mapper session"
    rationale: "Multiple facts from same source should share one Source node"

metrics:
  duration: 7 min
  completed: 2026-03-13

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | FactMapper - fact/entity/source/investigation to graph nodes and edges | 90ece9a | fact_mapper.py, test_fact_mapper.py |
| 2 | RelationshipExtractor - hybrid rule-based and LLM relationship extraction | 654a1d2 | relationship_extractor.py, test_relationship_extractor.py |

## What Was Built

### fact_mapper.py (326 lines)
- **FactMapper**: Session-scoped mapper that converts ExtractedFact + optional VerificationResult + optional FactClassification into GraphNode/GraphEdge objects
- **Entity resolution**: `_entity_canonical_map` deduplicates entities by canonical name; `_entity_aliases` accumulates all text variants; produces single node per resolved entity with `aliases` list and `resolution_confidence=1.0`
- **Source dedup**: `_seen_sources` prevents duplicate Source nodes across multiple `map_fact` calls
- **Investigation dedup**: `_investigation_node_created` flag ensures one Investigation node per mapper instance
- **map_fact()**: Creates Fact node (with quality, temporal, verification, classification properties), Entity nodes, Source node, Investigation node, plus MENTIONS/SOURCED_FROM/PART_OF/VERIFIED_BY edges
- **map_facts_batch()**: Aggregates across multiple facts with shared entity resolution

### relationship_extractor.py (504 lines)
- **RelationshipExtractor**: Hybrid rule-based + LLM relationship extractor
- **Rule-based extraction** (`_extract_rule_based`): Derives edges from existing metadata:
  - CORROBORATES: From CONFIRMED verification with 2+ supporting evidence + matching content
  - CONTRADICTS: From REFUTED verification with related_fact_id, or from FactRelationship.type="contradicts"
  - SUPERSEDES: From SUPERSEDED verification with temporal contradiction_type
  - RELATED_TO: From FactRelationship.type in (supports, elaborates)
  - LOCATED_AT: From PERSON/ORG + LOCATION entity co-occurrence (weight: state=0.8, event=0.7)
- **LLM-based extraction** (`_extract_llm_based`): Gated behind `config.llm_relationship_extraction`
  - Builds prompt from fact + nearby facts (shared entities, capped at 10)
  - Derives CAUSES, PRECEDES, ATTRIBUTED_TO edges with base weight 0.4
  - Uses `google.genai.Client` for Gemini 2.0 Flash
  - Graceful degradation: catches all exceptions, returns empty list, logs warning
- **Cross-investigation detection** (`extract_cross_investigation`): Exact canonical name match across investigations, creates RELATED_TO edges with `cross_investigation=True`
- **Edge deduplication**: `_deduplicate_edges` merges by (source_id, target_id, edge_type), keeping higher weight

### Test Coverage
- **test_fact_mapper.py** (458 lines, 20 tests): Node counts, edge types, property propagation, entity resolution, alias accumulation, missing provenance, verification/classification propagation, batch mapping, temporal markers, investigation/source dedup
- **test_relationship_extractor.py** (558 lines, 19 tests): Rule-based CORROBORATES/CONTRADICTS/SUPERSEDES/LOCATED_AT/RELATED_TO, LLM disabled gate, LLM enabled (mocked), LLM failure degradation, edge dedup, cross-investigation detection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Cross-investigation interface change**
- **Found during:** Task 2
- **Issue:** Plan specified `extract_cross_investigation` taking `adapter: GraphAdapter` for querying. However, the GraphAdapter Protocol only has high-level query methods -- no method to query entities by canonical name across investigations. Coupling directly to an adapter would require either adding a new Protocol method or doing raw Cypher (breaking NetworkX compatibility).
- **Fix:** Changed interface to accept `other_investigation_entities: dict[str, list[str]]` -- a pre-computed mapping of canonical names to investigation IDs. The calling layer (GraphIngestor in 09-04) will query the adapter and pass the dict. This is more testable and adapter-agnostic.
- **Files modified:** relationship_extractor.py, test_relationship_extractor.py
- **Commit:** 654a1d2

## Verification Results

```
tests/agents/sifters/graph/ - 39 tests, all passed
FactMapper importable: OK
RelationshipExtractor importable: OK
fact_mapper.py: 326 lines (>= 150)
relationship_extractor.py: 504 lines (>= 150)
test_fact_mapper.py: 458 lines (>= 80)
test_relationship_extractor.py: 558 lines (>= 80)

Key links verified:
  fact_mapper.py -> fact_schema.py: imports ExtractedFact
  fact_mapper.py -> graph/schema.py: imports GraphNode, GraphEdge
  relationship_extractor.py -> verification_schema.py: imports VerificationResult, VerificationStatus
  relationship_extractor.py -> graph_config.py: reads llm_relationship_extraction flag

ALL VERIFICATIONS PASSED
```

## Next Plan Readiness

09-04 (GraphIngestor) can now:
- Import `FactMapper` for converting facts to graph nodes/edges
- Import `RelationshipExtractor` for deriving semantic edges
- Use `map_facts_batch()` for efficient batch ingestion
- Use `extract_relationships()` for per-fact edge derivation
- Use `extract_cross_investigation()` with pre-queried entity map
