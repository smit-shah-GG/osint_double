"""Fact consolidator for deduplication and variant linking.

This sifter agent takes extracted facts and consolidates them:
1. Hash deduplication - exact content match (same claim text)
2. Semantic deduplication - similar claims from different sources (optional)

Per CONTEXT.md 0.3 threshold:
- Below 0.3: discard (too low confidence/similarity)
- Above 0.3: link as variants, preserve all source provenance

Multiple sources reporting the same claim is different from one source.
Consolidation preserves this corroboration signal by linking variants
rather than deleting duplicates.

Features:
- Multi-layer deduplication (hash, semantic)
- 0.3 similarity threshold per CONTEXT.md
- Variant linking preserves corroboration
- Integration with FactStore
- Optional embedding model support for semantic similarity
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.data_management.schemas import ExtractedFact


@dataclass
class ConsolidationStats:
    """Statistics tracking for consolidation process."""

    total_input: int = 0
    hash_duplicates: int = 0
    semantic_duplicates: int = 0
    below_threshold: int = 0
    unique_claims: int = 0

    def to_dict(self) -> Dict[str, int]:
        """Convert stats to dictionary."""
        return {
            "total_input": self.total_input,
            "hash_duplicates": self.hash_duplicates,
            "semantic_duplicates": self.semantic_duplicates,
            "below_threshold": self.below_threshold,
            "unique_claims": self.unique_claims,
        }


class FactConsolidator(BaseSifter):
    """
    Consolidator for deduplicating and linking variant facts.

    Implements multi-layer deduplication:
    - Layer 1: Content hash (exact text match)
    - Layer 2: Semantic similarity (optional, requires embeddings)

    Per CONTEXT.md decision on deduplication:
    1. Identify semantic duplicates (same claim from different sources)
    2. Apply low threshold (0.3) - below threshold, discard
    3. Above threshold: link as variants, preserve all source provenance

    Usage:
        consolidator = FactConsolidator()
        result = await consolidator.sift({
            'facts': [fact1, fact2, ...],
            'investigation_id': 'inv-001'
        })
        # Returns list of canonical facts with variants linked
    """

    # CONTEXT.md specified threshold
    DEFAULT_SEMANTIC_THRESHOLD = 0.3

    def __init__(
        self,
        fact_store: Optional["FactStore"] = None,  # noqa: F821
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
        enable_semantic: bool = False,
        embedding_model: Optional[Any] = None,
        **kwargs
    ):
        """
        Initialize fact consolidator.

        Args:
            fact_store: Optional FactStore for persistence
            semantic_threshold: Minimum similarity for variant linking (default 0.3)
            enable_semantic: Enable semantic similarity (requires embedding model)
            embedding_model: Optional embedding model for semantic similarity
            **kwargs: Additional arguments passed to BaseSifter
        """
        super().__init__(
            name="FactConsolidator",
            description="Deduplicates and consolidates extracted facts",
            **kwargs
        )
        self.fact_store = fact_store
        self.semantic_threshold = semantic_threshold
        self.enable_semantic = enable_semantic and embedding_model is not None
        self.embedding_model = embedding_model

        self.logger = logger.bind(component="FactConsolidator")
        self.stats = ConsolidationStats()

        # Working indexes (reset per batch)
        self._hash_to_canonical: Dict[str, str] = {}  # hash -> canonical_fact_id
        self._canonical_facts: Dict[str, Dict[str, Any]] = {}  # fact_id -> fact
        self._embeddings_cache: Dict[str, List[float]] = {}  # fact_id -> embedding

        self.logger.info(
            "FactConsolidator initialized",
            semantic_enabled=self.enable_semantic,
            threshold=self.semantic_threshold
        )

    async def sift(self, content: dict) -> List[Dict[str, Any]]:
        """
        Consolidate facts by deduplicating and linking variants.

        Args:
            content: Dict with:
                - facts: List of fact dicts or ExtractedFact objects
                - investigation_id: Investigation identifier (required for storage)
                - min_confidence: Optional minimum confidence filter (default 0.0)

        Returns:
            List of canonical fact dicts with variants linked
        """
        facts = content.get("facts", [])
        investigation_id = content.get("investigation_id", "")
        min_confidence = content.get("min_confidence", 0.0)

        if not facts:
            self.logger.debug("No facts to consolidate")
            return []

        # Reset working state for this batch
        self._reset_working_state()
        self.stats.total_input = len(facts)

        # Convert to dicts if needed
        fact_dicts = self._normalize_facts(facts)

        # Filter by minimum confidence if specified
        if min_confidence > 0.0:
            fact_dicts = self._filter_by_confidence(fact_dicts, min_confidence)
            self.stats.below_threshold = self.stats.total_input - len(fact_dicts)

        # Layer 1: Hash deduplication
        consolidated = self._dedupe_by_hash(fact_dicts)

        # Layer 2: Semantic deduplication (if enabled)
        if self.enable_semantic:
            consolidated = await self._dedupe_semantic(consolidated)

        self.stats.unique_claims = len(consolidated)

        # Store if fact_store provided
        if self.fact_store and investigation_id:
            await self._persist_facts(investigation_id, consolidated)

        self.logger.info(
            f"Consolidated {self.stats.total_input} -> {len(consolidated)} facts",
            **self.stats.to_dict()
        )

        return consolidated

    def _reset_working_state(self) -> None:
        """Reset working indexes for a new batch."""
        self._hash_to_canonical = {}
        self._canonical_facts = {}
        self._embeddings_cache = {}
        self.stats = ConsolidationStats()

    def _normalize_facts(self, facts: List[Any]) -> List[Dict[str, Any]]:
        """Convert facts to dict form, ensuring content_hash exists."""
        normalized = []
        for fact in facts:
            if isinstance(fact, ExtractedFact):
                fact_dict = fact.model_dump()
            elif isinstance(fact, dict):
                fact_dict = fact.copy()
            else:
                self.logger.warning(f"Unknown fact type: {type(fact)}, skipping")
                continue

            # Ensure content_hash exists
            if not fact_dict.get("content_hash"):
                claim_text = self._extract_claim_text(fact_dict)
                fact_dict["content_hash"] = self._compute_hash(claim_text)

            # Ensure variants list exists
            if "variants" not in fact_dict:
                fact_dict["variants"] = []

            normalized.append(fact_dict)
        return normalized

    def _extract_claim_text(self, fact: Dict[str, Any]) -> str:
        """Extract claim text from fact dict."""
        claim = fact.get("claim", {})
        if isinstance(claim, dict):
            return claim.get("text", "")
        return str(claim) if claim else ""

    def _compute_hash(self, text: str) -> str:
        """Compute SHA256 hash of text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _filter_by_confidence(
        self,
        facts: List[Dict[str, Any]],
        min_confidence: float
    ) -> List[Dict[str, Any]]:
        """Filter facts by minimum extraction confidence."""
        filtered = []
        for fact in facts:
            quality = fact.get("quality", {})
            if isinstance(quality, dict):
                confidence = quality.get("extraction_confidence", 1.0)
            else:
                confidence = 1.0

            if confidence >= min_confidence:
                filtered.append(fact)
            else:
                self.logger.debug(
                    f"Filtering fact {fact.get('fact_id')} "
                    f"with confidence {confidence} < {min_confidence}"
                )
        return filtered

    def _dedupe_by_hash(
        self,
        facts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate facts by content hash.

        Same hash = same claim text = exact duplicate.
        First occurrence becomes canonical, others become variants.

        Returns list of canonical facts with variants linked.
        """
        for fact in facts:
            fact_id = fact.get("fact_id", "")
            content_hash = fact.get("content_hash", "")

            if not fact_id:
                self.logger.warning("Fact missing fact_id, skipping")
                continue

            if content_hash in self._hash_to_canonical:
                # This is a duplicate - link as variant
                canonical_id = self._hash_to_canonical[content_hash]
                canonical = self._canonical_facts[canonical_id]

                # Link variant
                if fact_id not in canonical["variants"]:
                    canonical["variants"].append(fact_id)

                # Merge provenance if needed
                self._merge_provenance(canonical, fact)

                self.stats.hash_duplicates += 1
                self.logger.debug(
                    f"Hash duplicate: {fact_id} -> {canonical_id}"
                )
            else:
                # This is a new unique claim
                self._hash_to_canonical[content_hash] = fact_id
                self._canonical_facts[fact_id] = fact

        return list(self._canonical_facts.values())

    async def _dedupe_semantic(
        self,
        facts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Semantic deduplication using embedding similarity.

        Facts with similarity >= threshold become variants.
        This catches paraphrases and rewordings.

        Note: Currently requires external embedding model.
        Without model, this is a no-op returning input unchanged.
        """
        if not self.enable_semantic or not self.embedding_model:
            return facts

        # Generate embeddings for all facts
        for fact in facts:
            fact_id = fact.get("fact_id", "")
            claim_text = self._extract_claim_text(fact)

            if fact_id and claim_text:
                try:
                    embedding = await self._get_embedding(claim_text)
                    self._embeddings_cache[fact_id] = embedding
                except Exception as e:
                    self.logger.warning(f"Failed to embed {fact_id}: {e}")

        # Compare all pairs and link similar facts
        fact_ids = list(self._canonical_facts.keys())
        canonical_set = set(fact_ids)  # Track which are still canonical

        for i, id_a in enumerate(fact_ids):
            if id_a not in canonical_set:
                continue

            emb_a = self._embeddings_cache.get(id_a)
            if not emb_a:
                continue

            for id_b in fact_ids[i + 1:]:
                if id_b not in canonical_set:
                    continue

                emb_b = self._embeddings_cache.get(id_b)
                if not emb_b:
                    continue

                similarity = self._cosine_similarity(emb_a, emb_b)

                if similarity >= self.semantic_threshold:
                    # Link id_b as variant of id_a
                    fact_a = self._canonical_facts[id_a]
                    fact_b = self._canonical_facts[id_b]

                    if id_b not in fact_a["variants"]:
                        fact_a["variants"].append(id_b)

                    self._merge_provenance(fact_a, fact_b)
                    canonical_set.discard(id_b)
                    self.stats.semantic_duplicates += 1

                    self.logger.debug(
                        f"Semantic match ({similarity:.2f}): {id_b} -> {id_a}"
                    )

        # Return only canonical facts
        return [
            self._canonical_facts[fid]
            for fid in canonical_set
            if fid in self._canonical_facts
        ]

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using configured model."""
        if not self.embedding_model:
            raise ValueError("No embedding model configured")

        # This is a generic interface - actual implementation depends on model
        if hasattr(self.embedding_model, "embed_async"):
            return await self.embedding_model.embed_async(text)
        elif hasattr(self.embedding_model, "embed"):
            return self.embedding_model.embed(text)
        else:
            raise ValueError("Embedding model must have embed() or embed_async()")

    def _cosine_similarity(
        self,
        vec_a: List[float],
        vec_b: List[float]
    ) -> float:
        """Compute cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _merge_provenance(
        self,
        canonical: Dict[str, Any],
        variant: Dict[str, Any]
    ) -> None:
        """
        Merge provenance from variant into canonical fact.

        Per CONTEXT.md: Multiple sources for same claim is corroboration signal.
        We preserve all sources by tracking them in the canonical fact.
        """
        # Get source IDs
        canonical_prov = canonical.get("provenance", {})
        variant_prov = variant.get("provenance", {})

        # Initialize additional_sources list if not present
        if "additional_sources" not in canonical:
            canonical["additional_sources"] = []

        # Extract variant's source info
        variant_source = {
            "source_id": variant_prov.get("source_id") if isinstance(variant_prov, dict) else None,
            "fact_id": variant.get("fact_id"),
        }

        if variant_source["source_id"]:
            canonical["additional_sources"].append(variant_source)

    async def _persist_facts(
        self,
        investigation_id: str,
        facts: List[Dict[str, Any]]
    ) -> None:
        """Persist consolidated facts to FactStore."""
        if not self.fact_store:
            return

        try:
            stats = await self.fact_store.save_facts(investigation_id, facts)
            self.logger.debug(
                f"Persisted facts to store",
                investigation_id=investigation_id,
                **stats
            )
        except Exception as e:
            self.logger.error(f"Failed to persist facts: {e}", exc_info=True)

    def get_capabilities(self) -> List[str]:
        """Return consolidator capabilities."""
        caps = ["fact_consolidation", "deduplication", "variant_linking"]
        if self.enable_semantic:
            caps.append("semantic_deduplication")
        return caps

    def get_consolidation_stats(self) -> Dict[str, Any]:
        """Return current consolidation statistics."""
        return self.stats.to_dict()
