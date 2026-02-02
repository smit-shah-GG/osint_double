---
status: passed
phase: 06-fact-extraction-pipeline
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md, 06-04-SUMMARY.md]
started: 2026-02-03T12:00:00Z
completed: 2026-02-03T01:15:00Z
---

## Current Test

number: complete
name: UAT Complete
expected: All tests executed
awaiting: none

## Tests

### 1. ExtractedFact minimal creation
expected: Running `uv run python -c "from osint_system.data_management.schemas import ExtractedFact, Claim; f = ExtractedFact(claim=Claim(text='Test')); print(f.fact_id[:8], f.content_hash[:16])"` prints a UUID prefix and SHA256 hash prefix (auto-computed from claim text).
result: pass

### 2. Entity markers in claim format
expected: Running `uv run python -c "from osint_system.data_management.schemas import ExtractedFact, Claim, Entity, EntityType; f = ExtractedFact(claim=Claim(text='[E1:Putin] visited Beijing'), entities=[Entity(id='E1', text='Putin', type=EntityType.PERSON)]); print(f.claim.text)"` outputs `[E1:Putin] visited Beijing` showing entity marker format.
result: pass

### 3. FactExtractionAgent initialization
expected: Running `uv run python -c "from osint_system.agents.sifters import FactExtractionAgent; a = FactExtractionAgent(gemini_client=None); print(a.name, len(a.get_capabilities()))"` prints `FactExtractionAgent N` (agent name and capabilities count).
result: pass
note: Requires GEMINI_API_KEY env var. Agent has 7 capabilities (more than originally expected 5).

### 4. Content hash deduplication
expected: Running `uv run python -c "from osint_system.data_management.schemas import ExtractedFact, Claim; f1 = ExtractedFact(claim=Claim(text='Same claim')); f2 = ExtractedFact(claim=Claim(text='Same claim')); print(f1.content_hash == f2.content_hash)"` outputs `True` (same text = same hash).
result: pass

### 5. FactStore save and retrieve
expected: Running `uv run python -c "import asyncio; from osint_system.data_management.fact_store import FactStore; async def t(): s=FactStore(); await s.save_facts('inv1',[{'fact_id':'f1','content_hash':'h1','claim':{'text':'T'}}]); print((await s.get_fact('inv1','f1'))['fact_id']); asyncio.run(t())"` prints `f1`.
result: pass

### 6. FactConsolidator deduplication
expected: Running `uv run python -c "import asyncio; from osint_system.agents.sifters import FactConsolidator; async def t(): c=FactConsolidator(); r=await c.sift({'facts':[{'fact_id':'f1','claim':{'text':'Same'}},{'fact_id':'f2','claim':{'text':'Same'}}],'investigation_id':'i1'}); print(len(r)); asyncio.run(t())"` prints `1` (two identical claims deduplicated to one).
result: pass
note: Requires GEMINI_API_KEY env var.

### 7. ExtractionPipeline initialization
expected: Running `uv run python -c "from osint_system.pipelines import ExtractionPipeline; p = ExtractionPipeline(); print(p.batch_size)"` prints `10` (default batch size).
result: pass

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
skipped: 0

## Gaps

None - all tests pass when GEMINI_API_KEY environment variable is set.

## Notes

- Tests 3 and 6 require GEMINI_API_KEY env var due to import chain (agents/__init__.py -> simple_agent.py -> gemini_client.py -> settings.py)
- This is expected behavior for a system that requires LLM access
- Test files saved to `tests/uat/` for regression testing
