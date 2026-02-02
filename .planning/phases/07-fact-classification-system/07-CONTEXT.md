# Phase 7: Fact Classification System - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Categorize extracted facts into impact tiers (critical/less-critical) with orthogonal trust status (verified/dubious). Compute credibility scores using a sophisticated multi-factor formula. Classify dubious facts by failure type (not magnitude) to enable targeted Phase 8 verification subroutines.

</domain>

<decisions>
## Implementation Decisions

### Tier Definitions

**Impact vs Trust are orthogonal dimensions:**
- Impact tier: critical / less-critical (based on geopolitical significance)
- Trust status: verified / dubious (based on credibility scoring + logic gates)
- A fact can be both "critical" AND "dubious" — high-impact dubious facts get priority verification

**Impact assessment:**
- Based on impact potential, NOT relevance to objective
- Both entity significance AND event type contribute
- Investigation-relative: same fact may be critical in one investigation, less-critical in another
- Temporal relevance is context-dependent (investigation determines if recency matters)

**Dubious classification uses multi-flag system:**
- Separate flags: source_dubious + content_dubious (not a single score)
- Either flag triggers dubious status (conservative approach)
- Classifications are dynamic — update as new information arrives

### Credibility Scoring

**Core Formula:**
```
Claim Score = Σ(SourceCred × Proximity × Precision)
```

**Components:**
- **SourceCred**: Source credibility (hybrid: pre-configured baselines for known sources, learn from scratch for unknown)
- **Proximity**: Exponential decay with hop_count — `0.7^hop` (moderate decay, secondary sources still meaningful)
- **Precision**: Entity count + temporal precision + verifiability signals (documents cited, quotes attributed)

**Source credibility factors:**
- Source type baseline (wire services > official gov > major news > regional > social > anonymous)
- Track record (historical accuracy from verification outcomes)
- Additional factors: independence, transparency, editorial process

**Root Source Diversity (anti-circular-reporting):**
- Detect shared roots via explicit attribution tracking (provenance chain from Phase 6)
- Use logarithmic decay for echo scoring:

```
Total Score = S_root + (α · log₁₀(1 + Σ S_echoes))
```

- α ≈ 0.2 (dampening factor)
- First quality echo (NYT picks up AP) adds real value
- 100th echo (bot aggregator) adds near-zero
- Botnet-proof: 1M low-quality bots get crushed by log function

### Classification Triggers (The Taxonomy of Doubt)

**CRITICAL: Use Boolean Logic Gates, NOT weighted formulas.**

Dubious classification identifies the *species* of doubt, not magnitude. Each species triggers a specific Phase 8 subroutine.

| Species | Trigger (Logic Gate) | Signal | Phase 8 Action |
|---------|---------------------|--------|----------------|
| **Phantom** (Structural Failure) | `hop_count > 2 AND primary_source IS NULL` | Echo without speaker | Trace back to find root |
| **Fog** (Attribution Failure) | `claim_clarity < 0.5 OR attribution ~= "sources say"` | Speaker is mumbling | Find harder version of claim |
| **Anomaly** (Coherence Failure) | `contradiction_count > 0` | Trusted systems disagree | Arbitrate (time/location/context) |
| **Noise** (Reputation Failure) | `source_credibility < 0.3` | Known unreliable source | Contain, archive as disinfo signature |

**Flag behavior:**
- Flags are independent — a fact can have multiple flags (Phantom + Fog)
- Each flag triggers its own Phase 8 subroutine
- Priority score = Impact × Fixability (high-impact fixable claims get priority)

**Noise handling:**
- Does NOT enter Phase 8 individual verification queue
- Batch analysis only — aggregate for pattern detection (disinfo campaign signatures)
- Turns garbage into meta-level signal

**Anomaly (contradiction) detection:**
- Tiered approach: within-investigation for all facts, cross-investigation for critical-tier only

### Output Format

**Classification stored as separate record (not on ExtractedFact):**
- Facts remain immutable
- Classifications are mutable (dynamic re-classification)
- Links fact_id to classification data

**Classification record schema (full audit trail):**
```python
{
    "fact_id": str,
    "investigation_id": str,
    "impact_tier": "critical" | "less_critical",
    "dubious_flags": ["phantom", "fog", "anomaly", "noise"],  # Can be empty or multiple
    "priority_score": float,  # Impact × Fixability
    "credibility_score": float,
    "credibility_breakdown": {
        "s_root": float,
        "s_echoes_sum": float,
        "proximity_scores": [...],
        "precision_scores": [...],
        "echo_bonus": float  # The log-dampened contribution
    },
    "classification_reasoning": {
        "phantom": "hop_count=4, no primary_source found",
        "fog": "attribution contains 'reportedly'"
    },
    "history": [
        {
            "timestamp": datetime,
            "previous_state": {...},
            "trigger": "new corroborating source added"
        }
    ],
    "classified_at": datetime,
    "updated_at": datetime
}
```

**Indexing for Phase 8:**
- Priority queue (ordered by priority_score) for general processing
- Flag-type indexes (all Phantoms, all Fogs, etc.) for specialized subroutines
- Both indexes maintained

### Claude's Discretion

- Exact thresholds for claim_clarity boundary (< 0.5 is guidance, can tune)
- Attribution pattern matching implementation ("sources say", "reportedly", etc.)
- Specific data structures for indexes
- Anomaly detection algorithm details

</decisions>

<specifics>
## Specific Ideas

**The logarithmic echo formula prevents gaming:**
- Fact A (Reuters only): Score 0.9
- Fact B (Reuters + 3 Major Papers): Score ~1.1 (verified by editorial review)
- Fact C (Reuters + 10,000 Twitter Bots): Score ~1.15 (effectively capped)

**Design philosophy:** Detail over compactness. In OSINT, losing signal is worse than carrying extra data. This reverberates through:
- Multi-flag dubious system (preserves WHY something is dubious)
- Full credibility breakdown (not just final score)
- Complete audit trail (not just current state)
- Component storage (enables debugging and formula evolution)

**The Taxonomy of Doubt prevents resource misallocation:**
- Phase 8 receives specific job tickets ("Fix the structure" vs "Fix the attribution")
- Noise gets batch-analyzed for patterns, not individually verified
- High-value Anomalies (contradictions between trusted sources) don't compete with garbage for attention

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 07-fact-classification-system*
*Context gathered: 2026-02-03*
