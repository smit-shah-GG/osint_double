"""URL management with normalization and deduplication for crawler coordination.

Uses yarl for RFC-compliant URL normalization. Provides investigation-scoped
deduplication to prevent redundant crawling while allowing the same URL to
appear in different investigations.
"""

from typing import Optional, Set, Dict
from dataclasses import dataclass, field
from datetime import datetime
import logging

from yarl import URL


logger = logging.getLogger(__name__)


# Tracking parameters to strip during normalization (common analytics/tracking params)
TRACKING_PARAMS: frozenset[str] = frozenset({
    # Google Analytics
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    # Facebook/Meta
    "fbclid", "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    # Twitter
    "twclid",
    # Microsoft/Bing
    "msclkid",
    # Google Ads
    "gclid", "gclsrc", "dclid",
    # Other common trackers
    "ref", "source", "mc_cid", "mc_eid", "oly_enc_id", "oly_anon_id",
    "_ga", "_gl", "_hsenc", "_hsmi", "hsCtaTracking",
    "vero_id", "nr_email_referer", "mkt_tok",
})


@dataclass
class URLEntry:
    """Metadata for a tracked URL."""
    normalized_url: str
    original_url: str
    domain: str
    investigation_id: str
    first_seen: datetime = field(default_factory=datetime.utcnow)
    crawl_count: int = 1


class URLManager:
    """
    Manages URL normalization and deduplication across investigations.

    Provides O(1) duplicate detection using investigation-scoped URL tracking.
    Uses yarl for RFC-compliant URL normalization including:
    - Protocol normalization (http/https handling)
    - Tracking parameter removal
    - Path normalization (trailing slashes, case)
    - Query parameter sorting
    - Fragment removal

    Same URL can appear in different investigations, preventing cross-investigation
    pollution while ensuring deduplication within an investigation.
    """

    def __init__(self, strip_tracking_params: bool = True, normalize_case: bool = True):
        """
        Initialize URL manager.

        Args:
            strip_tracking_params: Remove tracking parameters during normalization
            normalize_case: Lowercase domain during normalization
        """
        self.strip_tracking_params = strip_tracking_params
        self.normalize_case = normalize_case

        # investigation_id -> set of normalized URLs for O(1) lookup
        self._seen_urls: Dict[str, Set[str]] = {}

        # Detailed tracking: (investigation_id, normalized_url) -> URLEntry
        self._url_entries: Dict[tuple[str, str], URLEntry] = {}

        logger.info(
            f"URLManager initialized (strip_tracking={strip_tracking_params}, "
            f"normalize_case={normalize_case})"
        )

    def normalize_url(self, url: str) -> str:
        """
        Normalize URL for consistent comparison.

        Normalization steps:
        1. Parse with yarl (handles encoding, IDNA)
        2. Lowercase host if normalize_case enabled
        3. Remove tracking parameters
        4. Remove fragments
        5. Normalize path (remove trailing slash unless root)
        6. Sort query parameters
        7. Reconstruct canonical URL

        Args:
            url: Raw URL string

        Returns:
            Normalized URL string suitable for deduplication

        Raises:
            ValueError: If URL cannot be parsed
        """
        try:
            parsed = URL(url)
        except Exception as e:
            logger.warning(f"Failed to parse URL '{url}': {e}")
            raise ValueError(f"Invalid URL: {url}") from e

        # Handle relative URLs by returning as-is
        if not parsed.is_absolute():
            logger.debug(f"Relative URL passed, returning as-is: {url}")
            return url

        # Lowercase host if configured
        host = parsed.host or ""
        if self.normalize_case and host:
            host = host.lower()

        # Filter query parameters
        if parsed.query_string:
            filtered_params = []
            for key in sorted(parsed.query.keys()):
                if not self.strip_tracking_params or key.lower() not in TRACKING_PARAMS:
                    filtered_params.append((key, parsed.query[key]))

            # Reconstruct query string
            if filtered_params:
                query_string = "&".join(f"{k}={v}" for k, v in filtered_params)
            else:
                query_string = ""
        else:
            query_string = ""

        # Normalize path
        path = parsed.path or "/"
        # Remove trailing slash unless root path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Reconstruct URL without fragment
        scheme = parsed.scheme or "https"
        port = parsed.port

        # Only include port if non-standard
        if port and ((scheme == "http" and port != 80) or (scheme == "https" and port != 443)):
            host_with_port = f"{host}:{port}"
        else:
            host_with_port = host

        # Build normalized URL
        if query_string:
            normalized = f"{scheme}://{host_with_port}{path}?{query_string}"
        else:
            normalized = f"{scheme}://{host_with_port}{path}"

        return normalized

    def extract_domain(self, url: str) -> str:
        """
        Extract domain from URL for authority scoring.

        Handles subdomains by returning the full host. For TLD+1 extraction,
        use a library like tldextract.

        Args:
            url: URL string

        Returns:
            Domain string (e.g., "www.reuters.com")

        Raises:
            ValueError: If URL cannot be parsed
        """
        try:
            parsed = URL(url)
            domain = parsed.host or ""
            if self.normalize_case:
                domain = domain.lower()
            return domain
        except Exception as e:
            logger.warning(f"Failed to extract domain from '{url}': {e}")
            raise ValueError(f"Cannot extract domain from: {url}") from e

    def add_url(self, url: str, investigation_id: str) -> bool:
        """
        Add URL to tracking for an investigation.

        If URL is already tracked for this investigation, increments crawl count.
        If URL is new, creates entry and returns True.

        Args:
            url: URL to track
            investigation_id: Investigation identifier for scoping

        Returns:
            True if URL was new for this investigation, False if duplicate
        """
        normalized = self.normalize_url(url)

        # Ensure investigation set exists
        if investigation_id not in self._seen_urls:
            self._seen_urls[investigation_id] = set()

        # Check for duplicate
        if normalized in self._seen_urls[investigation_id]:
            # Update crawl count
            key = (investigation_id, normalized)
            if key in self._url_entries:
                self._url_entries[key].crawl_count += 1
            logger.debug(f"Duplicate URL for investigation {investigation_id}: {url}")
            return False

        # Add new URL
        self._seen_urls[investigation_id].add(normalized)
        self._url_entries[(investigation_id, normalized)] = URLEntry(
            normalized_url=normalized,
            original_url=url,
            domain=self.extract_domain(url),
            investigation_id=investigation_id,
        )

        logger.debug(f"Added URL for investigation {investigation_id}: {normalized}")
        return True

    def is_duplicate(self, url: str, investigation_id: str) -> bool:
        """
        Check if URL is a duplicate for an investigation.

        O(1) lookup using normalized URL in set.

        Args:
            url: URL to check
            investigation_id: Investigation identifier for scoping

        Returns:
            True if URL already seen for this investigation
        """
        try:
            normalized = self.normalize_url(url)
        except ValueError:
            # Invalid URLs are considered unique to allow error handling downstream
            return False

        if investigation_id not in self._seen_urls:
            return False

        return normalized in self._seen_urls[investigation_id]

    def get_entry(self, url: str, investigation_id: str) -> Optional[URLEntry]:
        """
        Get URL entry with metadata if tracked.

        Args:
            url: URL to look up
            investigation_id: Investigation identifier

        Returns:
            URLEntry if found, None otherwise
        """
        try:
            normalized = self.normalize_url(url)
        except ValueError:
            return None

        return self._url_entries.get((investigation_id, normalized))

    def get_investigation_urls(self, investigation_id: str) -> Set[str]:
        """
        Get all normalized URLs for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Set of normalized URL strings
        """
        return self._seen_urls.get(investigation_id, set()).copy()

    def get_url_count(self, investigation_id: str) -> int:
        """
        Get count of unique URLs for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Number of unique URLs
        """
        return len(self._seen_urls.get(investigation_id, set()))

    def clear_investigation(self, investigation_id: str) -> int:
        """
        Clear all URL tracking for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Number of URLs cleared
        """
        count = len(self._seen_urls.get(investigation_id, set()))

        if investigation_id in self._seen_urls:
            del self._seen_urls[investigation_id]

        # Clean up entries
        keys_to_remove = [
            key for key in self._url_entries
            if key[0] == investigation_id
        ]
        for key in keys_to_remove:
            del self._url_entries[key]

        logger.info(f"Cleared {count} URLs for investigation {investigation_id}")
        return count

    def get_stats(self) -> Dict[str, int]:
        """
        Get URL manager statistics.

        Returns:
            Dictionary with counts by investigation and total
        """
        stats = {
            "total_urls": len(self._url_entries),
            "investigations": len(self._seen_urls),
        }
        for inv_id, urls in self._seen_urls.items():
            stats[f"investigation_{inv_id}"] = len(urls)
        return stats
