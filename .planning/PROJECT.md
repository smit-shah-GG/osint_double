# OSINT Intelligence System

## What This Is

An LLM-powered multi-agent intelligence gathering system for geopolitical analysis, featuring a crawler-sifter architecture that automates the acquisition, extraction, classification, and verification of facts from open sources. The system produces structured intelligence products with comprehensive analytical summaries for personal research use.

## Core Value

Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.

## Current Milestone: v2.0 — Production Hardening & Frontend

**Goal:** Harden the pipeline for reliable unattended operation, build a production-quality Next.js frontend, and prepare for deployment.

**Target features:**
- Crawler robustness (UA rotation, RSS fallback, Playwright for JS/paywall sites)
- Extraction quality (fix validation drops, improve fact yield, prompt optimization)
- Verification coverage (NOISE threshold tuning, refutation queries, graph ingestion of unverifiable facts)
- Analysis & reporting polish (source authority, model configurability, template improvements)
- Full Next.js + shadcn/ui frontend (investigation launch, live progress, report viewer, graph viz, source management)
- Infrastructure (persistent storage, rate limiting, cost tracking, YAML config profiles, deployment)

## Requirements

### Validated

<!-- Shipped and confirmed valuable in v1.0. -->

- ✓ End-to-end pipeline from objective input to final analysis report — v1.0
- ✓ Hierarchical multi-agent system with Planning, Crawler, and Sifter cohorts — v1.0
- ✓ Fact extraction from news sources with metadata preservation — v1.0
- ✓ Three-tier fact classification (critical, less-than-critical, dubious) — v1.0
- ✓ Automated verification loop for dubious facts — v1.0
- ✓ LLM-powered analysis and conclusion generation — v1.0
- ✓ Knowledge graph integration for enhanced context and reasoning — v1.0
- ✓ DuckDuckGo verification with snippet stance detection — v1.0 UAT
- ✓ OpenRouter integration with model fallback chains — v1.0 UAT
- ✓ CLI-based investigation runner — v1.0 UAT

### Active

<!-- Current scope for v2.0. -->

- [ ] Crawler hardening (UA rotation, RSS fallback, Playwright, paywall handling)
- [ ] Extraction quality fixes (claim_type validation, fact yield improvement)
- [ ] Verification coverage expansion (NOISE threshold, refutation queries, UNVERIFIABLE ingestion)
- [ ] Source authority differentiation in reports
- [ ] Next.js + shadcn/ui frontend with investigation management
- [ ] Live pipeline progress dashboard
- [ ] Knowledge graph visualization
- [ ] Investigation history and comparison
- [ ] Source management UI
- [ ] Persistent storage (SQLite/PostgreSQL)
- [ ] Cost tracking and token monitoring
- [ ] Configuration profiles (YAML-based)
- [ ] Deployable to server

### Out of Scope

- Visual/audio content analysis — Text-based intelligence only
- Predictive capabilities — No trend forecasting
- Dark web sources — Security and ethical complexities deferred
- Real-time streaming — Batch processing sufficient
- Multi-language support — English-only sources
- Mobile app — Web-first
- Multi-user auth — Personal use only for now

## Context

v1.0 milestone (10 phases, 45 plans) built the complete pipeline from scratch. UAT sessions on 2026-03-15 and 2026-03-20 proved the pipeline works end-to-end but exposed crawler fragility (30-40% of high-value sources blocked), extraction quality variance across models, low verification coverage (most facts classified NOISE), and the need for a proper frontend beyond the basic HTMX dashboard.

The system currently runs investigations in ~4-8 minutes via CLI, produces quality intelligence reports, and costs ~$0.50-2.00 per run depending on model selection. OpenRouter integration provides model flexibility with fallback chains.

Key UAT finding: the system is functionally complete but operationally fragile. v2.0 focuses on making it reliable, presentable, and deployable.

## Constraints

- **Backend**: Python 3.11+, uv package manager (mandatory)
- **Frontend**: Next.js + shadcn/ui (TypeScript)
- **LLM**: OpenRouter as primary provider, direct Gemini API as fallback
- **Framework**: LangChain/LangGraph for agent orchestration
- **Personal Use**: For personal research only
- **Source Access**: Must respect robots.txt, rate limits, and terms of service

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangChain/LangGraph framework | Best supervisor-worker patterns, cycles support for verification loop | ✓ Good |
| News sources first | Most reliable, well-structured, easier API/RSS access | ✓ Good |
| Fully automated verification | Maximize system autonomy | ✓ Good |
| Knowledge graph in beta | Significant value for fact relationships | ✓ Good |
| OpenRouter over direct Gemini | No quota limits, model flexibility, fallback chains | ✓ Good |
| DuckDuckGo over Serper | Free, no API key, sufficient quality for verification | ✓ Good |
| Next.js + shadcn/ui for frontend | Data-dense dashboard needs, modern component library | — Pending |
| Gemini 3.1 Flash Lite for extraction | Cheapest option but low fact yield (~4/article) | ⚠️ Revisit |

---
*Last updated: 2026-03-20 after v2.0 milestone start*
