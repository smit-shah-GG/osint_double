"""SQLAlchemy ORM models for the OSINT system.

All model classes are imported here so that ``Base.metadata``
contains the full schema when Alembic autogenerate runs.

CRITICAL: Every new model MUST be imported in this file. If a model
is defined but not imported here, ``alembic revision --autogenerate``
will silently skip its table (Pitfall 6 from RESEARCH.md).
"""

from osint_system.data_management.models.base import Base
from osint_system.data_management.models.article import ArticleModel
from osint_system.data_management.models.fact import FactModel
from osint_system.data_management.models.classification import ClassificationModel
from osint_system.data_management.models.verification import VerificationModel
from osint_system.data_management.models.report import ReportModel
from osint_system.data_management.models.entity import EntityModel

__all__ = [
    "Base",
    "ArticleModel",
    "FactModel",
    "ClassificationModel",
    "VerificationModel",
    "ReportModel",
    "EntityModel",
]
