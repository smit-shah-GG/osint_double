"""Pipeline modules for orchestrating multi-component data flows.

This package contains pipeline classes that wire together agents, stores,
and processing components to create end-to-end data flows.

Pipelines handle:
- Component initialization and wiring
- Batch processing and error handling
- Progress tracking and statistics
- Graceful degradation on component failures
"""

from osint_system.pipelines.extraction_pipeline import ExtractionPipeline

__all__ = ["ExtractionPipeline"]
