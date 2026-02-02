# Roadmap: OSINT Intelligence System

## Overview

A comprehensive journey from zero to a fully functional LLM-powered multi-agent intelligence gathering system. Starting with foundational infrastructure, we'll build specialized crawler and sifter agent cohorts, implement sophisticated fact extraction and verification loops, integrate a knowledge graph for enhanced reasoning, and culminate in a powerful analysis engine that produces actionable geopolitical intelligence from diverse open sources.

## Domain Expertise

None

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Environment Setup** - Python environment, Gemini API, project structure ✓ Complete
- [x] **Phase 2: Base Agent Architecture** - Core agent classes, MCP/A2A protocols ✓ Complete
- [x] **Phase 3: Planning & Orchestration Agent** - Task decomposition and hierarchical coordination ✓ Complete
- [x] **Phase 4: News Crawler Implementation** - RSS feeds and news API integration ✓ Complete
- [x] **Phase 5: Extended Crawler Cohort** - Social media and document crawlers ✓ Complete
- [x] **Phase 6: Fact Extraction Pipeline** - LLM-powered fact identification and extraction ✓ Complete
- [ ] **Phase 7: Fact Classification System** - Three-tier categorization and credibility assessment
- [ ] **Phase 8: Verification Loop** - Dubious fact investigation and re-classification
- [ ] **Phase 9: Knowledge Graph Integration** - Graph database and relationship mapping
- [ ] **Phase 10: Analysis & Reporting Engine** - Synthesis, multiple outputs, dashboard

## Phase Details

### Phase 1: Foundation & Environment Setup
**Goal**: Establish development environment with all base dependencies and API connectivity
**Depends on**: Nothing (first phase)
**Research**: Unlikely (established patterns)
**Plans**: 4 plans (4/4 complete)
**Status**: Complete ✓
**Completed**: 2026-01-10

Plans:
- [x] 01-01: Set up uv environment and core dependencies ✓
- [x] 01-02: Configure Pydantic settings and logging infrastructure ✓
- [x] 01-03: Integrate Gemini API with rate limiting ✓
- [x] 01-04: Basic agent proof-of-concept ✓

### Phase 2: Base Agent Architecture
**Goal**: Create foundational agent classes with MCP tool integration and A2A communication
**Depends on**: Phase 1
**Research**: Complete ✓
**Research topics**: MCP protocol implementation, A2A communication patterns, agent interface design
**Plans**: 4 plans (4/4 complete)
**Status**: Complete ✓
**Completed**: 2026-01-11

Plans:
- [x] 02-01: Dependencies & Enhanced BaseAgent ✓
- [x] 02-02: Message Bus & Registry ✓
- [x] 02-03: LangGraph Orchestration ✓
- [x] 02-04: MCP Tool Server & Integration ✓

### Phase 3: Planning & Orchestration Agent
**Goal**: Build the central coordinator for objective decomposition and task distribution
**Depends on**: Phase 2
**Research**: Complete ✓
**Research topics**: LangGraph supervisor patterns, task queue implementations, hierarchical workflows
**Plans**: 3 plans (3/3 complete)
**Status**: Complete ✓
**Completed**: 2026-01-12

Plans:
- [x] 03-01: Implement Planning Agent with LangGraph ✓
- [x] 03-02: Create task queue and distribution system ✓
- [x] 03-03: Build supervisor-worker coordination patterns ✓

### Phase 4: News Crawler Implementation
**Goal**: Deploy first crawler for news sources with filtering and metadata preservation
**Depends on**: Phase 3
**Research**: Complete ✓
**Research topics**: News API options (NewsAPI, GDELT), RSS feed parsing, rate limiting strategies
**Plans**: 4 plans (4/4 complete)
**Status**: Complete ✓
**Completed**: 2026-01-13

Plans:
- [x] 04-01: Implement NewsFeedAgent base functionality ✓
- [x] 04-02: Integrate RSS feeds and NewsAPI ✓
- [x] 04-03: Add filtering and metadata extraction ✓
- [x] 04-04: Data routing and integration ✓

### Phase 5: Extended Crawler Cohort
**Goal**: Expand data acquisition with social media and document crawlers
**Depends on**: Phase 4
**Research**: Complete ✓
**Research topics**: Reddit API authentication, web scraping best practices, document parsing libraries
**Plans**: 6 plans (6/6 complete)
**Status**: Complete ✓
**Completed**: 2026-02-01

Plans:
- [x] 05-01: Reddit crawler setup ✓
- [x] 05-02: Reddit data collection and integration ✓
- [x] 05-03: Document crawler setup ✓
- [x] 05-04: Web scraper enhancement ✓
- [x] 05-05: Crawler coordination system ✓
- [x] 05-06: Integration testing ✓

### Phase 6: Fact Extraction Pipeline
**Goal**: Extract discrete, verifiable facts from raw text with structured output per CONTEXT.md schema
**Depends on**: Phase 5
**Research**: Unlikely (internal LLM prompting using established patterns)
**Plans**: 4 plans (4/4 complete)
**Status**: Complete ✓
**Completed**: 2026-02-03

Plans:
- [x] 06-01: Pydantic schemas for fact output (ExtractedFact, Entity, Provenance) ✓
- [x] 06-02: FactExtractionAgent with Gemini prompts ✓
- [x] 06-03: FactStore and FactConsolidator for dedup/storage ✓
- [x] 06-04: ExtractionPipeline bridging crawler output to fact extraction ✓

### Phase 7: Fact Classification System
**Goal**: Categorize facts into critical/less-critical/dubious tiers with credibility scoring
**Depends on**: Phase 6
**Research**: Unlikely (internal logic and prompt engineering)
**Plans**: 3 plans

Plans:
- [ ] 07-01: Implement FactClassificationAgent
- [ ] 07-02: Build source credibility assessment
- [ ] 07-03: Create classification rules and prompts

### Phase 8: Verification Loop
**Goal**: Investigate and resolve dubious facts through targeted searches
**Depends on**: Phase 7
**Research**: Unlikely (uses existing crawler and sifter components)
**Plans**: 4 plans

Plans:
- [ ] 08-01: Create VerificationAgent architecture
- [ ] 08-02: Implement targeted query generation
- [ ] 08-03: Build evidence aggregation system
- [ ] 08-04: Create re-classification logic

### Phase 9: Knowledge Graph Integration
**Goal**: Store verified facts in graph database with relationship extraction
**Depends on**: Phase 8
**Research**: Likely (technology selection)
**Research topics**: Graph database options (Neo4j, NetworkX), fact-to-graph mapping patterns, query languages
**Plans**: 5 plans

Plans:
- [ ] 09-01: Set up graph database infrastructure
- [ ] 09-02: Implement fact-to-graph mapping
- [ ] 09-03: Create relationship extraction
- [ ] 09-04: Build graph query interface
- [ ] 09-05: Integrate with verification loop

### Phase 10: Analysis & Reporting Engine
**Goal**: Generate intelligence products with multiple output formats and dashboard
**Depends on**: Phase 9
**Research**: Unlikely (internal patterns, uses existing components)
**Plans**: 5 plans

Plans:
- [ ] 10-01: Build AnalysisReportingAgent
- [ ] 10-02: Implement synthesis and pattern detection
- [ ] 10-03: Create database output format
- [ ] 10-04: Build report generation system
- [ ] 10-05: Develop dashboard interface

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Environment Setup | 4/4 | Complete ✓ | 2026-01-10 |
| 2. Base Agent Architecture | 4/4 | Complete ✓ | 2026-01-12 |
| 3. Planning & Orchestration Agent | 3/3 | Complete ✓ | 2026-01-12 |
| 4. News Crawler Implementation | 4/4 | Complete ✓ | 2026-01-13 |
| 5. Extended Crawler Cohort | 6/6 | Complete ✓ | 2026-02-01 |
| 6. Fact Extraction Pipeline | 4/4 | Complete ✓ | 2026-02-03 |
| 7. Fact Classification System | 0/3 | Not started | - |
| 8. Verification Loop | 0/4 | Not started | - |
| 9. Knowledge Graph Integration | 0/5 | Not started | - |
| 10. Analysis & Reporting Engine | 0/5 | Not started | - |
