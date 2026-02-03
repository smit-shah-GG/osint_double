"""Data management package for OSINT system.

Provides storage adapters and schemas for:
- Facts (ExtractedFact) - immutable extraction output
- Classifications (FactClassification) - mutable classification records
- Articles - raw crawled content

Storage adapters:
- FactStore: Investigation-scoped fact persistence
- ClassificationStore: Investigation-scoped classification persistence
- ArticleStore: Investigation-scoped article persistence
"""

from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.classification_store import ClassificationStore

__all__ = [
    "FactStore",
    "ClassificationStore",
]
