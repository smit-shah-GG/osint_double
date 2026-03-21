"""Fact listing and detail endpoints with classification/verification enrichment.

Flattens internal nested fact dicts (claim, provenance sub-dicts) into clean
``FactResponse`` models by joining data from FactStore, ClassificationStore,
and VerificationStore.  Internal pipeline schemas are never exposed.

Endpoints:
    GET /investigations/{investigation_id}/facts
    GET /investigations/{investigation_id}/facts/{fact_id}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from osint_system.api.errors import NotFoundError
from osint_system.api.schemas import FactResponse, PaginatedResponse

router = APIRouter(prefix="/api/v1")


# -- Helpers ---------------------------------------------------------------


def _get_stores(request: Request, investigation_id: str) -> tuple:
    """Resolve fact/classification/verification stores for an investigation.

    Checks ``app.state.investigation_stores[investigation_id]`` first (API
    runner pattern), then falls back to stores mounted directly on
    ``app.state`` (serve.py compatibility).

    Raises:
        NotFoundError: If no stores are found for the investigation.
    """
    inv_stores = getattr(request.app.state, "investigation_stores", {})
    if investigation_id in inv_stores:
        stores = inv_stores[investigation_id]
        return (
            stores.get("fact_store"),
            stores.get("classification_store"),
            stores.get("verification_store"),
        )

    # Fallback: stores mounted directly on app.state
    fact_store = getattr(request.app.state, "fact_store", None)
    if fact_store is not None:
        return (
            fact_store,
            getattr(request.app.state, "classification_store", None),
            getattr(request.app.state, "verification_store", None),
        )

    raise NotFoundError(
        detail=f"Investigation '{investigation_id}' not found.",
    )


async def _enrich_fact(
    fact: dict[str, Any],
    classification_store: Any,
    verification_store: Any,
    investigation_id: str,
) -> FactResponse:
    """Build a flat ``FactResponse`` from an internal fact dict + store lookups.

    The internal fact structure (from FactStore) uses nested dicts:
    - ``fact["claim"]`` -> dict with ``text``, ``claim_type``
    - ``fact["provenance"]`` -> dict with ``source_id``, ``source_type``

    Classification and verification data are optional -- not every fact has
    been classified or verified.
    """
    fact_id = fact.get("fact_id", "")

    # -- Extract claim fields -----------------------------------------------
    claim = fact.get("claim", {})
    if isinstance(claim, dict):
        claim_text = claim.get("text", "")
        claim_type = claim.get("claim_type", "unknown")
    else:
        claim_text = str(claim)
        claim_type = "unknown"

    # -- Extract provenance fields ------------------------------------------
    provenance = fact.get("provenance", {})
    if isinstance(provenance, dict):
        source_id = provenance.get("source_id")
        source_type = provenance.get("source_type")
    else:
        source_id = None
        source_type = None

    # -- Classification enrichment ------------------------------------------
    impact_tier: str | None = None
    if classification_store is not None:
        classification = await classification_store.get_classification(
            investigation_id, fact_id
        )
        if classification is not None:
            # ClassificationStore returns dicts (model_dump(mode="json"))
            if isinstance(classification, dict):
                impact_tier = classification.get("impact_tier")
            else:
                # Pydantic model path (defensive)
                tier = getattr(classification, "impact_tier", None)
                impact_tier = tier.value if hasattr(tier, "value") else str(tier) if tier else None

    # -- Verification enrichment --------------------------------------------
    verification_status: str | None = None
    if verification_store is not None:
        verification = await verification_store.get_result(
            investigation_id, fact_id
        )
        if verification is not None:
            status = getattr(verification, "status", None)
            if status is not None:
                verification_status = (
                    status.value if hasattr(status, "value") else str(status)
                )

    return FactResponse(
        fact_id=fact_id,
        claim_text=claim_text,
        claim_type=claim_type,
        source_id=source_id,
        source_type=source_type,
        extraction_confidence=fact.get("extraction_confidence"),
        impact_tier=impact_tier,
        verification_status=verification_status,
        created_at=fact.get("stored_at"),
    )


# -- Endpoints -------------------------------------------------------------


@router.get(
    "/investigations/{investigation_id}/facts",
    response_model=PaginatedResponse[FactResponse],
)
async def list_facts(
    request: Request,
    investigation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> PaginatedResponse[FactResponse]:
    """List enriched facts for an investigation with pagination."""
    fact_store, classification_store, verification_store = _get_stores(
        request, investigation_id
    )

    result = await fact_store.retrieve_by_investigation(investigation_id)
    raw_facts: list[dict[str, Any]] = result.get("facts", [])

    enriched: list[FactResponse] = []
    for fact in raw_facts:
        enriched.append(
            await _enrich_fact(
                fact, classification_store, verification_store, investigation_id
            )
        )

    return PaginatedResponse[FactResponse].from_items(enriched, page, page_size)


@router.get(
    "/investigations/{investigation_id}/facts/{fact_id}",
    response_model=FactResponse,
)
async def get_fact(
    request: Request,
    investigation_id: str,
    fact_id: str,
) -> FactResponse:
    """Retrieve a single enriched fact by ID."""
    fact_store, classification_store, verification_store = _get_stores(
        request, investigation_id
    )

    raw_fact = await fact_store.get_fact(investigation_id, fact_id)
    if raw_fact is None:
        raise NotFoundError(
            detail=f"Fact '{fact_id}' not found in investigation '{investigation_id}'.",
        )

    return await _enrich_fact(
        raw_fact, classification_store, verification_store, investigation_id
    )
