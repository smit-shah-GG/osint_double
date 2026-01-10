# OSINT Intelligence System

## What This Is

An LLM-powered multi-agent intelligence gathering system for geopolitical analysis, featuring a crawler-sifter architecture that automates the acquisition, extraction, classification, and verification of facts from open sources. The system produces structured intelligence products with comprehensive analytical summaries for personal research use.

## Core Value

Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. Building toward these. -->

- [ ] End-to-end pipeline from objective input to final analysis report
- [ ] Hierarchical multi-agent system with Planning, Crawler, and Sifter cohorts
- [ ] Fact extraction from news sources with metadata preservation
- [ ] Three-tier fact classification (critical, less-than-critical, dubious)
- [ ] Automated verification loop for dubious facts
- [ ] LLM-powered analysis and conclusion generation
- [ ] Multiple output formats (database, reports, API access)
- [ ] Hybrid triggering system (manual queries + automated monitoring)
- [ ] MCP integration for crawler tools and A2A for agent collaboration
- [ ] Knowledge graph integration for enhanced context and reasoning

### Out of Scope

- Visual/audio content analysis — Beta focuses on text-based intelligence only
- Predictive capabilities — No trend forecasting or future predictions in beta
- Dark web sources — Security and ethical complexities deferred
- Real-time streaming — Near-real-time batch processing is sufficient for beta
- Multi-language support — English-only sources initially

## Context

Building a sophisticated OSINT system inspired by traditional intelligence analysis workflows but powered by modern LLM capabilities. The crawler-sifter architecture separates data acquisition from analytical processing, allowing for specialized optimization of each phase.

The system targets geopolitical events comprehensively - conflicts, political changes, economic events, and all major developments. Initial implementation focuses on news sources (RSS feeds, major outlets) as they provide reliable, structured content ideal for testing the core pipeline.

With ample resources available, the focus is on building the best possible proof-of-concept emphasizing deep accuracy (Gemini Pro for critical tasks), broad coverage (multiple source types), and smart reasoning (knowledge graph, sophisticated agent collaboration).

## Constraints

- **Technology**: Python 3.11+, uv package manager (mandatory), Gemini API for LLMs
- **Framework**: LangChain/LangGraph for agent orchestration and workflows
- **Architecture**: Hybrid MCP/A2A within hierarchical structure required
- **Personal Use**: For personal research only, simplifying privacy/ethical concerns
- **Source Access**: Must respect robots.txt, rate limits, and terms of service

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangChain/LangGraph framework | Best supervisor-worker patterns, cycles support for verification loop, mature ecosystem | — Pending |
| News sources first | Most reliable, well-structured, easier API/RSS access for beta testing | — Pending |
| Fully automated verification | Maximize system autonomy, reduce human intervention needs | — Pending |
| Knowledge graph in beta | Resources available, significant value for fact relationships and context | — Pending |
| Gemini model tiering | Use Pro for analysis/verification, Flash for crawling/filtering | — Pending |

---
*Last updated: 2026-01-10 after initialization*