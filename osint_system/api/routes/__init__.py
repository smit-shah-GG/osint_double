"""API route modules for the OSINT investigation system.

Provides:
- ``investigations``: Investigation lifecycle CRUD, launch, cancel, regenerate.
- ``stream``: SSE event streaming with Last-Event-ID replay.
- ``facts``: Fact listing and detail with classification/verification enrichment.
- ``reports``: Report retrieval and version listing.
- ``sources``: Source inventory with domain aggregation.
- ``graph``: Knowledge graph nodes, edges, and query patterns.
"""
