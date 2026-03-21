"""JSON REST API layer for the OSINT investigation pipeline.

Exposes investigation lifecycle management, fact retrieval, report versioning,
source inventory, knowledge graph queries, and real-time SSE event streaming.

All API response models live in ``schemas.py`` and are decoupled from internal
pipeline schemas (ExtractedFact, VerificationResult, etc.).
"""
