# Milestones

## v1.0 — Core Pipeline (Complete)

**Completed:** 2026-03-14
**Phases:** 1-10 (45 plans)
**Duration:** 804 minutes

Built the complete OSINT pipeline from scratch:
- Foundation & environment setup
- Base agent architecture (MCP/A2A)
- Planning & orchestration agent
- News crawler (RSS + NewsAPI)
- Extended crawler cohort (Reddit, documents, web)
- Fact extraction pipeline (Gemini LLM)
- Fact classification system (3-tier + dubious detection)
- Verification loop (search + evidence aggregation)
- Knowledge graph integration (Neo4j/NetworkX)
- Analysis & reporting engine (synthesis + dashboard)

**UAT findings (2026-03-15, 2026-03-20):**
- Fixed NoneType crashes in classification
- Fixed credibility scoring (added 17 source baselines)
- Replaced Serper with DuckDuckGo for verification
- Added snippet stance detection for refutation
- Added OpenRouter integration with model fallback chains
- Fixed report template rendering
- Added store persistence and dashboard serving
- Made extraction async with concurrent semaphore
- First successful end-to-end runs with real data

**Last phase number:** 10
