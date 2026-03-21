"""MAGE graph algorithm invocation for Memgraph.

Provides Cypher query constants and an async runner for three MAGE algorithms:
PageRank (entity importance), Louvain community detection (entity clusters),
and betweenness centrality (broker/intermediary detection).

These algorithms run post-pipeline on the full graph. Investigation-scoped
subgraph projection via ``project()`` is deferred per RESEARCH.md open
question 3 -- full-graph execution is acceptable because investigations
do not share entity nodes.

The ``run_mage_analysis`` function accepts any ``GraphAdapter`` (via
``execute_cypher``) and degrades gracefully if MAGE modules are not
available (e.g., plain ``memgraph/memgraph`` image without MAGE).

Usage:
    from osint_system.data_management.graph.mage_algorithms import (
        run_mage_analysis,
    )

    results = await run_mage_analysis(adapter)
    # {"pagerank": 42, "communities": 8, "betweenness": 42}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from osint_system.data_management.graph.adapter import GraphAdapter

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MAGE algorithm Cypher queries
# ---------------------------------------------------------------------------

# PageRank: computes importance score for all nodes, stores as node.rank.
PAGERANK_QUERY: str = (
    "CALL pagerank.get() "
    "YIELD node, rank "
    "SET node.rank = rank "
    "RETURN count(node) AS nodes_ranked"
)

# Community detection (Louvain): assigns community IDs, stores as node.community.
COMMUNITY_DETECTION_QUERY: str = (
    "CALL community_detection.get() "
    "YIELD node, community_id "
    "SET node.community = community_id "
    "RETURN count(node) AS nodes_assigned"
)

# Betweenness centrality: computes bridging importance, stores as node.betweenness.
# Args: (TRUE, TRUE) = directed=True, normalized=True.
BETWEENNESS_QUERY: str = (
    "CALL betweenness_centrality.get(TRUE, TRUE) "
    "YIELD node, betweenness_centrality "
    "SET node.betweenness = betweenness_centrality "
    "RETURN count(node) AS nodes_scored"
)

# Mapping of algorithm name -> (query, result key in RETURN clause)
_ALGORITHMS: list[tuple[str, str, str]] = [
    ("pagerank", PAGERANK_QUERY, "nodes_ranked"),
    ("communities", COMMUNITY_DETECTION_QUERY, "nodes_assigned"),
    ("betweenness", BETWEENNESS_QUERY, "nodes_scored"),
]


async def run_mage_analysis(
    adapter: GraphAdapter,
    investigation_id: str | None = None,
) -> dict[str, int]:
    """Run all MAGE algorithms sequentially on the graph.

    Algorithms run sequentially (not parallel) because they modify graph
    state (SET node properties). Each algorithm is wrapped in try/except:
    if the MAGE module is not available, a warning is logged and the
    algorithm is skipped (graceful degradation).

    Args:
        adapter: Any GraphAdapter implementation with ``execute_cypher``.
            In practice, this is MemgraphAdapter -- NetworkXAdapter will
            raise NotImplementedError from execute_cypher.
        investigation_id: Reserved for future subgraph-scoped execution.
            Currently unused; full-graph algorithms run regardless.

    Returns:
        Dict mapping algorithm name to count of nodes processed.
        Skipped algorithms are not included in the result.
        Example: ``{"pagerank": 42, "communities": 8, "betweenness": 42}``
    """
    results: dict[str, int] = {}

    for algo_name, query, result_key in _ALGORITHMS:
        try:
            records = await adapter.execute_cypher(query)
            count = records[0][result_key] if records else 0
            results[algo_name] = count
            logger.info(
                "mage_algorithm_complete",
                algorithm=algo_name,
                nodes_processed=count,
            )
        except Exception as exc:
            # Graceful degradation: MAGE module not installed or other error.
            # Log warning and continue with remaining algorithms.
            logger.warning(
                "mage_algorithm_skipped",
                algorithm=algo_name,
                error=str(exc),
                hint="Ensure memgraph/memgraph-mage Docker image is used",
            )

    return results
