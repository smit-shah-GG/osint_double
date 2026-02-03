# Phase 8: Verification Loop - Context

**Gathered:** 2026-02-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Investigate and resolve dubious facts through targeted searches, producing confirmed, refuted, or unverifiable outcomes. This phase consumes the priority queue from Phase 7's classification system and outputs re-classified facts with evidence chains.

**Input interfaces from Phase 7:**
- `ClassificationStore.get_priority_queue(investigation_id)` — ordered by priority_score (impact × fixability)
- `ClassificationStore.get_by_flag(investigation_id, DubiousFlag)` — specialized retrieval per dubious species
- `DubiousResult.reasoning` — includes `contradicting_fact_ids` for ANOMALY resolution
- Fixability scores route verification effort to fixable claims first

**What this phase delivers:**
- VerificationAgent architecture for orchestrating targeted searches
- Query generation strategies specialized per dubious species (PHANTOM, FOG, ANOMALY)
- Evidence aggregation system with authority-weighted corroboration
- Re-classification logic producing new statuses: confirmed, refuted, unverifiable, superseded
- Automatic pipeline from classification → verification with human-in-the-loop for critical facts

**What this phase does NOT deliver:**
- Knowledge graph integration (Phase 9)
- Pattern detection across verified facts (Phase 10)
- New crawler implementations (uses existing Phase 4-5 crawlers)
- Changes to the classification schema (Phase 7 schemas are consumed, not modified)

</domain>

<decisions>
## Implementation Decisions

### Query Generation Strategy

#### Source-Chain Queries for PHANTOM Facts

**Decision:** PHANTOM facts (vague attribution like "officials say", "sources report") use source-chain queries that attempt to trace back to the root source.

**Rationale:** PHANTOM facts are dubious specifically because their attribution is vague or unverifiable. The core problem isn't that the claim itself is unbelievable—it's that we can't trace WHO actually said it. A claim like "senior officials say Russia is planning..." is useless for intelligence purposes unless we know which officials, from which agency, speaking in what capacity.

Source-chain queries directly attack this problem by:
1. Extracting the vague attribution phrase ("officials say", "sources familiar with")
2. Searching for the same claim with explicit attribution ("State Department spokesperson said", "Pentagon official John Smith confirmed")
3. Looking for the original press release, official statement, or interview that spawned the derivative reporting

This is more effective than entity-focused queries (which would just find more copies of the same vague claim) or claim-negation queries (which address truthfulness, not provenance). The PHANTOM problem is about sourcing, not veracity.

**Implementation guidance for researcher/planner:**
- Query templates should extract attribution phrases and search for explicit versions
- Prioritize wire services (AP, Reuters, AFP) as they often have direct source access
- Look for government press releases, official transcripts, named spokesperson quotes
- If root source is found, the PHANTOM flag can be cleared and fact re-assessed

#### Compound Approach for ANOMALY Facts

**Decision:** ANOMALY facts (contradictions detected between facts) use a compound query approach combining temporal context, authority arbitration, AND clarity enhancement—not just one dimension.

**Rationale:** Contradictions are inherently complex. A simplistic single-dimension approach would fail to resolve many real-world cases:

**Temporal dimension is necessary because:** Many apparent contradictions are actually temporal progressions. "Russia has 100,000 troops on the border" and "Russia has 150,000 troops on the border" aren't contradictions if the first is from January and the second from February—it's a buildup. Without temporal context, the system would incorrectly flag these as conflicting claims requiring arbitration.

**Authority dimension is necessary because:** When two sources genuinely disagree about a contemporaneous fact, we need to determine which source is more authoritative. A Pentagon press release about troop movements outweighs a Twitter analyst's estimate. The credibility framework from Phase 7 provides the authority scores, but verification needs to actively search for higher-authority sources that might settle the dispute.

**Clarity dimension is necessary because:** Sometimes contradictions arise from ambiguous language. "The attack killed dozens" vs "The attack killed 47" aren't contradictions—one is vague, one is specific. Verification should search for the clearer, more specific version of claims to resolve apparent conflicts that are really just precision differences.

**Why compound, not sequential:** These dimensions interact. A less authoritative source with temporal context might override a more authoritative source without it. A specific claim from a lower-authority source might be more useful than a vague claim from a higher-authority source. The verification agent must weigh all three simultaneously, not apply them as independent filters.

**Implementation guidance for researcher/planner:**
- Query generation should search for: (a) dated/timestamped versions of claims, (b) higher-authority sources on the same topic, (c) more specific/quantified versions of vague claims
- Resolution logic should score candidates on all three dimensions
- Arbitration output should explain which dimension(s) resolved the conflict
- Both facts in the contradiction should be updated: winner confirmed, loser marked appropriately

#### NOISE Facts Skip Individual Verification

**Decision:** NOISE facts do not enter the individual verification queue. They remain in batch analysis only.

**Rationale:** This decision is driven by both cost-effectiveness and conceptual correctness:

**Cost-effectiveness:** NOISE facts have low fixability scores (0.1) precisely because they're unlikely to be resolvable through targeted searches. They lack the specific, verifiable claims that make targeted queries effective. Spending API calls on NOISE verification has extremely low expected value compared to spending those same calls on PHANTOM/FOG/ANOMALY facts.

**Conceptual correctness:** NOISE facts are dubious not because of a specific fixable problem (vague attribution, unclear claim, contradiction) but because they lack signal entirely. They might be:
- Low-quality sources with no corroboration
- Vague claims with no specific assertions
- Social media noise without substantive content
- Potentially coordinated disinformation

For disinformation detection specifically, individual fact verification is the wrong approach. Disinformation is identified through *patterns*: multiple accounts posting similar claims, coordinated timing, network analysis. This requires batch analysis across the NOISE corpus, not per-fact verification.

**Implementation guidance for researcher/planner:**
- `get_priority_queue()` should exclude NOISE-only facts (already implemented in Phase 7)
- Batch analysis for NOISE facts is Phase 10 scope (pattern detection, disinfo signatures)
- NOISE facts remain in storage with their dubious flags for future batch processing
- If a NOISE fact is also flagged with another dubious type (e.g., PHANTOM + NOISE), it DOES enter verification for the non-NOISE flag

#### Three Query Variants Per Fact

**Decision:** Generate and attempt up to 3 query reformulations per dubious fact before abandoning that search angle.

**Rationale:** This balances thoroughness against cost and diminishing returns:

**Why more than 1:** A single query formulation often fails due to:
- Keyword mismatch (source uses different terminology than our query)
- Temporal scope issues (query too narrow or too broad in timeframe)
- Entity name variations (formal vs informal names, transliterations, abbreviations)

A fact about "DPRK missile tests" might need queries for "North Korea", "Pyongyang", "Kim regime", etc. to find relevant sources.

**Why not more than 3:** After 3 well-crafted reformulations, additional queries show severe diminishing returns. If entity-focused, exact-phrase, and broader-context queries all fail, the information likely isn't available in searchable sources. Further queries waste API calls and verification time.

**The 3 variant types:**
1. **Entity-focused:** Extract key entities and search directly ("Putin Ukraine statement January 2026")
2. **Exact phrase:** Search for distinctive phrases from the claim in quotes
3. **Broader context:** Widen scope to related events/topics that might contain the claim as a detail

**Implementation guidance for researcher/planner:**
- Query generator should produce all 3 variants upfront
- Execute in order: entity-focused (highest precision) → exact phrase → broader context
- Short-circuit if early query succeeds with sufficient evidence
- Track which query variant succeeded for future optimization
- After 3 failures, mark fact for "verification exhausted" processing

---

### Evidence Sufficiency

#### Authority-Weighted Corroboration Threshold

**Decision:** A dubious fact is confirmed when corroborated by either: (a) 1 high-authority source (wire service, .gov, .edu), OR (b) 2+ lower-authority sources from independent outlets.

**Rationale:** This leverages the credibility infrastructure from Phase 7 while recognizing that source authority fundamentally changes evidentiary requirements:

**Why high-authority sources can stand alone:** Wire services (AP, Reuters, AFP) have rigorous editorial standards, fact-checking processes, and legal exposure that makes them reliable. A single AP report citing named sources is more credible than five blog posts citing each other. Similarly, official government sources (.gov) and academic institutions (.edu) have reputational stakes that disincentivize fabrication.

From Phase 7's authority scores:
- Wire services: 0.9
- .gov/.edu domains: 0.85
- .org domains: 0.7
- Default news: 0.5
- Social media: 0.3

A source with authority ≥ 0.85 can single-handedly confirm a claim. Below that threshold, we need multiple independent sources.

**Why 2+ for lower-authority:** Two independent sources making the same claim dramatically reduces the probability of coordinated fabrication or shared error. "Independent" means different ownership/editorial chains—two articles from the same media conglomerate don't count as independent.

**Why not require 3+ across the board:** Overly strict requirements would leave too many facts unverifiable, especially for breaking news or niche topics where only 1-2 sources have coverage. The authority weighting provides appropriate skepticism without being paralyzingly cautious.

**Implementation guidance for researcher/planner:**
- Define "high authority" threshold (suggest: authority_score ≥ 0.85)
- Implement independence check: different domains AND different parent companies
- Query deduplication: same story syndicated to multiple outlets counts as 1 source
- Edge case: if original dubious fact came from high-authority source, we still need corroboration (something made it dubious in the first place—vague attribution, contradiction, etc.)

#### Verification Abandonment After 3 Failed Query Variants

**Decision:** If all 3 query reformulations return no relevant evidence, mark the fact as unverifiable and stop attempting verification.

**Rationale:** This directly implements the "3 query variants" decision in the abandonment logic:

**Why we need a clear stopping condition:** Without explicit abandonment criteria, verification could run indefinitely on difficult facts, consuming resources that should go to more tractable claims. The priority queue orders facts by fixability, but even high-fixability facts might prove unverifiable in practice.

**Why 3 is the right threshold:** Matches the query variant count decision. If our best entity-focused query, exact-phrase query, AND broader-context query all fail, we've exhausted the reasonable search space. Additional attempts would be shots in the dark.

**What "failed" means:** A query fails if it returns either:
- No results at all
- Results that don't contain relevant evidence about the claim (determined by the verification agent's relevance assessment)
- Results that are all from the same source as the original dubious fact (no new information)

**Implementation guidance for researcher/planner:**
- Track query attempts per fact in verification state
- After attempt 3, transition to "unverifiable" processing regardless of which query types were used
- Log all attempted queries and their outcomes for debugging/optimization
- Consider: should certain dubious species get more attempts? (Decided: no, keep uniform for simplicity)

#### New "Unverifiable" Status for Exhausted Verification

**Decision:** Facts that cannot be verified after all attempts receive a new "unverifiable" status, distinct from "dubious" (still being worked) and "noise" (low-value).

**Rationale:** Epistemic precision requires distinguishing between different types of uncertainty:

**"Dubious" means:** We have specific reasons to doubt this claim, and it's in the verification queue to be investigated.

**"Unverifiable" means:** We actively tried to verify this claim, used our best query strategies, and could not find sufficient evidence to confirm OR refute it. This is importantly different from:
- Not yet investigated (dubious, pending verification)
- Low-quality/low-signal (noise, not worth investigating)
- Found to be false (refuted)

**Why this matters for intelligence analysis:** An analyst needs to know the difference between "we haven't looked into this" and "we looked into this thoroughly and couldn't find evidence either way." The latter carries information: the claim may be:
- True but not publicly reported
- Too recent for sources to have covered
- From a domain where open sources are scarce
- Deliberately obscured

**Implications for downstream phases:**
- Phase 10 reporting should flag unverifiable facts as "unable to confirm or deny"
- Unverifiable facts shouldn't be treated as confirmed OR as false
- They may warrant human analyst attention for alternative verification methods (HUMINT, classified sources)

**Implementation guidance for researcher/planner:**
- Add VerificationStatus enum: PENDING, IN_PROGRESS, CONFIRMED, REFUTED, UNVERIFIABLE
- Unverifiable facts retain their original dubious flags as metadata (see later decision)
- Unverifiable facts exit the verification queue but remain in the fact store
- Consider: optional "retry_after" timestamp for facts that might become verifiable later (e.g., waiting for official report release)

#### Graduated Confidence Scoring Based on Evidence Quality

**Decision:** When evidence confirms a dubious fact, the confidence boost varies by evidence source authority:
- Wire service confirmation: +0.3
- Standard news outlet confirmation: +0.2
- Social media confirmation: +0.1
- Boosts are cumulative across multiple sources

**Rationale:** Not all confirmations are equal. A Reuters article directly quoting the original source is far more compelling than a Reddit thread agreeing with the claim.

**Why graduated, not binary:** Binary confirmation (yes/no) loses valuable information. Consider two confirmed facts:
- Fact A: Confirmed by AP, Reuters, and a government press release
- Fact B: Confirmed by two tweets and a blog post

Both are "confirmed" but carry very different epistemic weight. Graduated confidence preserves this distinction for downstream analysis.

**The specific values (+0.3/+0.2/+0.1):**

These are calibrated to the authority scoring from Phase 7:
- Wire services (authority 0.9): +0.3 is a major boost reflecting high reliability
- News outlets (authority 0.5-0.7): +0.2 is moderate, reflecting decent but not exceptional reliability
- Social media (authority 0.3): +0.1 is minimal, reflecting low reliability but non-zero signal

**Cumulative application:** Multiple confirmations stack. Three news outlets (+0.2 × 3 = +0.6) can equal or exceed a single wire service (+0.3) plus one news outlet (+0.2 = +0.5 total). This is intentional: volume of independent confirmation has evidentiary value.

**Cap considerations:** Confidence shouldn't exceed 1.0. If cumulative boosts push above 1.0, cap at 1.0. In practice, this means overwhelming confirmation saturates rather than overflows.

**Implementation guidance for researcher/planner:**
- Maintain source_type → confidence_boost mapping
- Track all confirming sources and their types
- Calculate final_confidence = original_confidence + sum(source_boosts)
- Cap at 1.0
- Store the confidence breakdown in classification history for audit

---

### Re-classification Logic

#### Re-assess Impact Tier with New Evidence

**Decision:** When a dubious fact is confirmed through verification, its impact tier (CRITICAL vs LESS_CRITICAL) is re-assessed based on the new evidence, not simply inherited from the original Phase 7 classification.

**Rationale:** Verification often reveals contextual information that changes a fact's significance:

**Promotion scenarios:**
- Original claim seemed minor, but verification revealed it's part of a larger significant pattern
- New sources provide additional context showing broader implications
- Named sources in verification are more senior/authoritative than expected

**Demotion scenarios:**
- Original claim seemed major, but verification revealed it's routine/expected
- Context from verification shows the claim is less novel than it appeared
- Scope of the claim turns out to be narrower than initially interpreted

**Why not "only promote, never demote":** This would create asymmetric bias. If verification can reveal a fact is MORE important than we thought, it can equally reveal a fact is LESS important than we thought. Epistemic integrity requires updating in both directions.

**Impact on verification priority queue:** This is a post-verification assessment. The priority queue still uses Phase 7's initial impact tier to prioritize verification order. Re-assessment happens after verification succeeds.

**Implementation guidance for researcher/planner:**
- After verification confirms a fact, run ImpactAssessor.assess() with new evidence included
- New evidence = original fact context + all confirming sources' content
- Compare new tier to original tier; log if changed
- Update ClassificationStore with new tier and reasoning

#### New "Refuted" Status for Disproven Facts

**Decision:** Facts where verification finds contradicting evidence (proving the claim is false) receive a new "refuted" status, distinct from unverifiable.

**Rationale:** Actively disproving a claim is fundamentally different from being unable to confirm it:

**Epistemic distinction:**
- "Unverifiable" = We couldn't find evidence either way
- "Refuted" = We found evidence the claim is false

**Why this matters:**

For analysts: A refuted claim carries information—it tells us someone made a false assertion. This could indicate:
- Honest error by the original source
- Deliberate disinformation
- Outdated information that was once true
- Misunderstanding or misquotation

All of these are analytically significant.

For the knowledge graph (Phase 9): Refuted facts should still be stored, potentially with edges like "contradicts" or "disproven_by" connecting them to the refuting evidence. Deleting them would lose valuable information about the information landscape.

**What constitutes refutation:**
- High-authority source explicitly denying the claim
- Official record contradicting the claimed fact
- Physical impossibility demonstrated (e.g., person claimed to be somewhere wasn't there per verified records)
- Temporal impossibility (event claimed before it could have happened)

**Implementation guidance for researcher/planner:**
- Add REFUTED to VerificationStatus enum
- Refutation requires evidence, not just absence of confirmation
- Store refuting_sources and refutation_reasoning in classification
- Refuted facts should be linkable to their refuting evidence for audit trail

#### Preserve Dubious Origin as Metadata After Confirmation

**Decision:** Even after a fact is confirmed through verification, its original dubious flag (PHANTOM, FOG, ANOMALY) is preserved as metadata, not cleared.

**Rationale:** Provenance transparency for intelligence analysts:

**The "origin: PHANTOM" signal:** When an analyst sees a confirmed fact that originated as PHANTOM, they know:
- This claim initially had vague attribution
- Verification successfully traced it to a root source
- The current confidence reflects that we did the work to verify

This is valuable context. A fact that was always well-sourced is different from a fact that started sketchy and was later confirmed. The latter tells us something about the information landscape—perhaps the original source was being cagey, or derivative reporting was sloppy, or there's a pattern of vague attribution from that beat.

**Audit trail for verification process:** Preserving the original flag lets us:
- Analyze which types of dubious facts are most often confirmed
- Identify sources that frequently produce PHANTOM/FOG claims that later verify
- Debug the classification system (are we flagging things as dubious that are easily verified? Maybe our thresholds are too sensitive)

**No analyst confusion:** The current status (CONFIRMED, REFUTED, UNVERIFIABLE) is the primary indicator. The dubious origin is secondary metadata, clearly labeled as "origin_flag" or similar, not mixed with current status.

**Implementation guidance for researcher/planner:**
- Add `origin_dubious_flags: List[DubiousFlag]` field to classification
- Populate at verification completion, before clearing current dubious status
- Current dubious_flags field cleared on confirmation/refutation
- Query interfaces should distinguish: get_by_current_flag() vs get_by_origin_flag()

#### Context-Dependent Resolution for Contradiction Losers

**Decision:** When an ANOMALY (contradiction) is resolved, the "losing" fact is handled based on contradiction type:
- Temporal contradictions → Loser marked "superseded" (was true, no longer current)
- Factual contradictions → Loser marked "refuted" (was never true)

**Rationale:** Not all contradictions are equal. Some represent change over time; others represent error.

**Temporal contradictions:**
- "100,000 troops on border" (January) vs "150,000 troops on border" (February)
- "Ceasefire in effect" (Monday) vs "Ceasefire collapsed" (Wednesday)
- "Minister X holds position" (2025) vs "Minister Y holds position" (2026)

In these cases, BOTH facts were true at their respective times. The earlier fact is "superseded"—not wrong, but no longer current. This preserves the historical record while indicating which fact reflects present reality.

**Factual contradictions:**
- "Attack killed 47" vs "Attack killed 12" (same event, different counts)
- "Meeting occurred in Moscow" vs "Meeting occurred in Geneva" (mutually exclusive)
- "Signed by President" vs "Vetoed by President" (can't be both)

Here, one claim is simply wrong. The loser is "refuted." There's no sense in which both were true at different times.

**Why this distinction matters:**

For temporal: Analysts studying historical patterns need superseded facts. Troop buildups, policy shifts, personnel changes—these are only visible if we preserve the historical record with appropriate annotations.

For factual: Marking a false claim as "superseded" would be misleading. It implies the claim was once valid, which it wasn't.

**Edge cases:**
- Mixed temporal-factual: If unclear, default to "refuted" (more conservative)
- Multiple contradictions: Each pair resolved independently
- Contradiction type detection: Part of the ANOMALY analysis in Phase 7, stored in reasoning

**Implementation guidance for researcher/planner:**
- Add SUPERSEDED to VerificationStatus enum
- Contradiction type should be available from Phase 7's AnomalyDetector output
- Resolution logic branches on contradiction_type
- Both winner and loser facts updated: winner → CONFIRMED, loser → REFUTED or SUPERSEDED
- Link winner and loser facts bidirectionally for graph integration (Phase 9)

---

### Verification Workflow

#### Parallel Batch Processing (5-10 Facts Concurrent)

**Decision:** Verification processes facts in parallel batches of 5-10 concurrent verifications, not sequentially one at a time.

**Rationale:** Speed optimization for investigation throughput:

**Why parallel:** Sequential verification is a bottleneck. If each fact takes 5-10 seconds to verify (query generation + search + relevance assessment), processing 100 dubious facts sequentially takes 8-16 minutes. Parallel batches of 10 reduce this to under 2 minutes.

**Why batched, not unbounded parallel:** Practical constraints:
- API rate limits: Gemini and search APIs have per-minute/per-second limits
- Resource management: Each verification needs state tracking; unbounded parallelism is memory-intensive
- Error handling: Batch failures are easier to retry than tracking hundreds of individual async tasks
- Observability: Batch completion points provide natural checkpoints for progress reporting

**Batch size 5-10:** This range balances throughput against the constraints above. Actual batch size can be tuned based on rate limit headroom.

**Priority within batches:** Batches are filled by priority order from the queue. The first batch contains the 10 highest-priority facts, second batch next 10, etc. This ensures we're always working on the most important facts first, even within parallel execution.

**Batch failure handling:** If some verifications in a batch fail (timeout, API error), successful ones are finalized, failures are retried in the next batch with a retry penalty (from Phase 3's priority scoring).

**Implementation guidance for researcher/planner:**
- Use asyncio.gather() with return_exceptions=True for batch execution
- Configurable batch_size with default 10
- Rate limiter shared across batch (from Phase 1 infrastructure)
- Batch completion triggers progress callback
- Respect priority order when filling batches

#### Automatic Pipeline from Classification to Verification

**Decision:** Verification runs automatically after classification completes—dubious facts flow directly into the verification queue without requiring explicit user/system trigger.

**Rationale:** Streamlined investigation flow:

**Why automatic:** The core value proposition of this OSINT system is automated intelligence processing. Requiring manual intervention between classification and verification defeats that purpose. An analyst initiates an investigation; the system should run through extraction → classification → verification → analysis automatically.

**Why not wait for explicit trigger:** Manual triggers add:
- Latency: Someone has to notice classification is done and start verification
- Operational burden: Another step to remember and execute
- Inconsistency: Different investigations might get different treatment

**Pipeline behavior:**
1. FactClassificationAgent.classify_investigation() completes
2. System automatically calls VerificationAgent.verify_investigation() with the same investigation_id
3. VerificationAgent pulls priority queue, processes batches
4. Results flow to Phase 9/10 (knowledge graph, analysis)

**Edge case: Re-classification after verification:**
If new facts arrive during verification (e.g., crawlers still running), they go through classification → verification as they arrive. Verification agent handles new queue entries dynamically.

**Emergency stop:** While automatic, the system should support investigation.cancel() or similar to abort a runaway verification loop.

**Implementation guidance for researcher/planner:**
- Pipeline orchestration in main investigation flow
- Message bus: classification.complete triggers verification.start
- Or: direct method chaining in InvestigationPipeline class
- Verification agent subscribes to new classification events even mid-verification
- Implement investigation.cancel() for emergency stop

#### Human-in-the-Loop for Critical Tier Verification Only

**Decision:** Human review is required before finalizing verification results for CRITICAL tier facts. LESS_CRITICAL and below are fully automated.

**Rationale:** Risk-proportionate human oversight:

**Why any human review:** From CLAUDE.md: "Human-in-the-loop for beta: Treat LLM analytical conclusions as drafts requiring human validation." High-stakes intelligence claims warrant human oversight before being treated as confirmed.

**Why only CRITICAL tier:** Reviewing every verified fact would be operationally infeasible and would negate the automation benefits. CRITICAL facts are, by definition, the ones that "directly address key investigative questions; high impact." These are worth human attention.

**What "human review" means:**
- System presents: original dubious fact, verification evidence, proposed new status, confidence score
- Human approves, rejects, or modifies the conclusion
- If rejected: fact remains dubious, potentially re-queued with different approach
- If modified: human provides corrected status/reasoning

**LESS_CRITICAL automation:** Lower-impact facts are verified and finalized automatically. They still appear in final reports but don't gate on human approval. This is acceptable because:
- Lower stakes if wrong
- Volume makes manual review impractical
- System confidence thresholds provide quality floor

**Implementation guidance for researcher/planner:**
- After verification, check fact's impact_tier
- CRITICAL: Queue for human review, await approval
- LESS_CRITICAL/other: Finalize automatically
- Human review interface: CLI prompts for beta, could be dashboard later
- Timeout on human review: If no response in X minutes, reminder; if no response in Y hours, flag for investigation owner

#### Fact-by-Fact Progress Updates

**Decision:** Verification logs each fact as it's verified, refuted, or marked unverifiable—not silent until complete, not batched summaries only.

**Rationale:** Real-time observability for long-running verifications:

**Why not silent:** Investigations may have hundreds of dubious facts. Silence until complete means:
- No feedback if something's stuck
- No ability to spot-check results mid-verification
- Anxiety-inducing UX for analyst waiting

**Why not batch summaries only:** Batch summaries (every 10 facts) are better than silence but still lose granularity. Individual fact updates let an analyst:
- See which specific facts are being worked
- Catch unexpected refutations immediately
- Understand verification patterns in real-time

**Update content per fact:**
- Fact ID and summary
- Original dubious flag(s)
- New status: CONFIRMED / REFUTED / UNVERIFIABLE
- Brief reasoning (1 line)
- Confidence score (for confirmed)

**Output channel:** Structured logging (structlog from Phase 1). Can be consumed by CLI, dashboard, or monitoring systems.

**Volume consideration:** With 100+ facts, individual updates create log volume. Options:
- Log verbosity levels: VERIFIED = INFO, failures = WARNING
- Summary statistics at batch completion in addition to individual logs
- UI can filter/aggregate if needed

**Implementation guidance for researcher/planner:**
- Emit structured log event after each fact verification completes
- Include: fact_id, claim_summary, original_flags, new_status, reasoning_summary, confidence
- Log level INFO for standard updates, WARNING for failures/unexpected
- Batch completion also logs aggregate stats: X confirmed, Y refuted, Z unverifiable
- Consider: optional quiet mode for non-interactive batch runs

---

### Claude's Discretion

The following areas were not explicitly discussed and are left to Claude's discretion during research and planning:

**Query construction details:**
- Exact query templates and syntax for each variant type
- Search API selection (Google Search, Bing, DuckDuckGo)
- Query length limits and truncation strategies

**Verification agent internal architecture:**
- Class structure and method decomposition
- State management during batch processing
- Error handling and retry backoff curves

**Performance optimization:**
- Caching of search results across similar queries
- Early termination if batch reaches high confirmation rate
- Adaptive batch sizing based on API rate limit headroom

**Edge case handling:**
- Facts with multiple dubious flags (e.g., PHANTOM + FOG)
- Circular contradictions (A contradicts B contradicts C contradicts A)
- Verification of already-confirmed facts (re-verification scenarios)

</decisions>

<specifics>
## Specific Ideas

**Source-chain tracing model:** The user emphasized that PHANTOM verification is fundamentally about finding WHO said something, not WHETHER it's true. This suggests query generation should heavily target:
- Official press releases and transcripts
- Named spokesperson quotes
- Original interviews and statements
- Wire service reports (they often have direct source access)

**Compound ANOMALY resolution:** User explicitly rejected single-dimension approaches. The verification agent must genuinely integrate temporal, authority, and clarity signals—not just check them in sequence. This might require a scoring function that weights all three, or a decision tree that considers combinations.

**Authority-weighted corroboration:** The existing Phase 7 authority scores (wire: 0.9, .gov/.edu: 0.85, .org: 0.7, social: 0.3) should directly map to the "high authority" threshold for single-source confirmation.

**Graduate confidence vs. binary:** The system should surface graduated confidence to analysts. Reports shouldn't just say "confirmed"—they should indicate "confirmed with high confidence (3 wire service sources)" vs "confirmed with moderate confidence (2 news outlets)".

</specifics>

<deferred>
## Deferred Ideas

**Pattern detection for NOISE facts:** Currently, NOISE facts are excluded from individual verification. Batch analysis for disinfo signatures, coordinated inauthentic behavior, and pattern detection is explicitly Phase 10 scope (Analysis & Reporting Engine).

**Verification from alternative sources (HUMINT, classified):** The current verification loop uses OSINT sources only (existing crawlers). Integration with non-open sources is out of scope for this project as defined.

**Re-verification triggers:** Currently, once a fact is confirmed/refuted/unverifiable, it's finalized. A future capability might re-verify facts when new contradicting information arrives or when source credibility changes. This could be a Phase 9 or 10 enhancement.

**Verification confidence decay:** Facts verified long ago might warrant re-verification as information landscapes change. Implementing "staleness" on verified facts and periodic re-verification is out of scope.

**Verification quality metrics:** Measuring verification accuracy (how often do our "confirmed" facts turn out to be wrong?) requires ground truth datasets and evaluation infrastructure. Deferred to post-MVP.

</deferred>

---

*Phase: 08-verification-loop*
*Context gathered: 2026-02-04*
