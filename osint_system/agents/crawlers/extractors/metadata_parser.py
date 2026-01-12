"""Comprehensive metadata extraction and normalization for articles.

Extracts and normalizes:
- Source credibility (from config)
- Temporal context (published date, retrieval time, age)
- Geographic context (location mentions, source origin)
- Author information (names, credentials)
- Article category/tags
- Content metrics (word count, reading time)
"""

import re
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ArticleMetadata:
    """Structured metadata for an article."""

    # Core identifiers
    url: str
    source_domain: str

    # Temporal context
    published_date: Optional[datetime] = None
    retrieval_time: Optional[datetime] = None
    content_age_hours: Optional[float] = None

    # Source credibility (configured per source)
    source_credibility: Optional[float] = None  # 0.0-1.0
    source_type: Optional[str] = None  # "mainstream", "alternative", "official"

    # Geographic context
    locations_mentioned: List[str] = None
    source_origin: Optional[str] = None  # Country/region of publication

    # Author information
    author_name: Optional[str] = None
    author_credentials: Optional[str] = None

    # Content categorization
    article_type: Optional[str] = None  # "breaking", "analysis", "opinion", "report"
    categories: List[str] = None
    tags: List[str] = None

    # Content metrics
    word_count: Optional[int] = None
    reading_time_minutes: Optional[float] = None

    # OpenGraph/Schema.org metadata
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    schema_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary format."""
        return {
            "url": self.url,
            "source_domain": self.source_domain,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "retrieval_time": self.retrieval_time.isoformat() if self.retrieval_time else None,
            "content_age_hours": self.content_age_hours,
            "source_credibility": self.source_credibility,
            "source_type": self.source_type,
            "locations_mentioned": self.locations_mentioned or [],
            "source_origin": self.source_origin,
            "author_name": self.author_name,
            "author_credentials": self.author_credentials,
            "article_type": self.article_type,
            "categories": self.categories or [],
            "tags": self.tags or [],
            "word_count": self.word_count,
            "reading_time_minutes": self.reading_time_minutes,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "schema_type": self.schema_type
        }


class MetadataParser:
    """Extracts and normalizes comprehensive metadata from articles."""

    # Source credibility configuration (extend as needed)
    SOURCE_CREDIBILITY = {
        "reuters.com": 0.95,
        "bbc.com": 0.95,
        "apnews.com": 0.95,
        "npr.org": 0.90,
        "theatlantic.com": 0.85,
        "wired.com": 0.85,
        "arstechnica.com": 0.85,
        "theverge.com": 0.80,
        "techcrunch.com": 0.80,
        "medium.com": 0.60,
        "reddit.com": 0.50,
        "twitter.com": 0.40,
        "x.com": 0.40,
    }

    SOURCE_TYPES = {
        "reuters.com": "mainstream",
        "bbc.com": "mainstream",
        "apnews.com": "mainstream",
        "npr.org": "mainstream",
        "theatlantic.com": "mainstream",
        "wired.com": "tech",
        "arstechnica.com": "tech",
        "theverge.com": "tech",
        "techcrunch.com": "tech",
        "medium.com": "platform",
        "reddit.com": "social",
        "twitter.com": "social",
        "x.com": "social",
    }

    # Common location patterns (extend for better coverage)
    LOCATION_PATTERNS = [
        r'\b(?:New York|London|Paris|Tokyo|Beijing|Moscow|Washington|Berlin|Sydney)\b',
        r'\b(?:USA|UK|EU|China|Russia|India|Brazil|Japan|Germany|France)\b',
        r'\b(?:United States|United Kingdom|European Union|Middle East|Asia|Africa)\b',
    ]

    # Article type detection patterns
    ARTICLE_TYPE_PATTERNS = {
        "breaking": r'\b(?:breaking|urgent|developing|just in|alert)\b',
        "analysis": r'\b(?:analysis|deep dive|examination|investigation|in-depth)\b',
        "opinion": r'\b(?:opinion|editorial|commentary|perspective|viewpoint)\b',
        "report": r'\b(?:report|study|survey|research|findings)\b',
    }

    def __init__(self):
        """Initialize metadata parser."""
        self.location_regex = re.compile('|'.join(self.LOCATION_PATTERNS), re.IGNORECASE)
        self.type_patterns = {
            type_name: re.compile(pattern, re.IGNORECASE)
            for type_name, pattern in self.ARTICLE_TYPE_PATTERNS.items()
        }

        if not BEAUTIFULSOUP_AVAILABLE:
            logger.warning("BeautifulSoup not available - HTML parsing will be limited")

    def parse(self, url: str, content: str, html: Optional[str] = None,
             published_date: Optional[datetime] = None) -> ArticleMetadata:
        """Parse and extract comprehensive metadata from article.

        Args:
            url: Article URL
            content: Article text content
            html: Optional HTML content for extracting OpenGraph/Schema.org
            published_date: Optional pre-parsed published date

        Returns:
            ArticleMetadata object with extracted information
        """
        metadata = ArticleMetadata(
            url=url,
            source_domain=self._extract_domain(url),
            retrieval_time=datetime.now(timezone.utc)
        )

        # Source credibility
        metadata.source_credibility = self.SOURCE_CREDIBILITY.get(
            metadata.source_domain, 0.5  # Default credibility
        )
        metadata.source_type = self.SOURCE_TYPES.get(
            metadata.source_domain, "unknown"
        )

        # Temporal context
        if published_date:
            metadata.published_date = self._normalize_datetime(published_date)
            metadata.content_age_hours = self._calculate_age_hours(metadata.published_date)

        # Geographic context
        metadata.locations_mentioned = self._extract_locations(content)
        metadata.source_origin = self._infer_source_origin(metadata.source_domain)

        # Author information (basic extraction from content)
        metadata.author_name = self._extract_author(content)

        # Article type detection
        metadata.article_type = self._detect_article_type(content)

        # Content metrics
        metadata.word_count = len(content.split())
        metadata.reading_time_minutes = round(metadata.word_count / 200, 1)  # 200 wpm average

        # HTML metadata extraction
        if html and BEAUTIFULSOUP_AVAILABLE:
            self._extract_html_metadata(html, metadata)

        # Categories and tags (basic extraction from content patterns)
        metadata.categories, metadata.tags = self._extract_categories_tags(content)

        return metadata

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception as e:
            logger.warning(f"Failed to extract domain from {url}: {e}")
            return "unknown"

    def _normalize_datetime(self, dt: datetime) -> datetime:
        """Normalize datetime to UTC with timezone info."""
        if dt.tzinfo is None:
            # Assume UTC if no timezone
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _calculate_age_hours(self, published_date: datetime) -> float:
        """Calculate content age in hours."""
        now = datetime.now(timezone.utc)
        age = now - published_date
        return age.total_seconds() / 3600

    def _extract_locations(self, content: str) -> List[str]:
        """Extract mentioned locations from content."""
        locations = set()
        matches = self.location_regex.findall(content)
        for match in matches:
            locations.add(match)
        return sorted(list(locations))

    def _infer_source_origin(self, domain: str) -> Optional[str]:
        """Infer geographic origin from domain."""
        # Simple mapping - extend as needed
        domain_origins = {
            ".uk": "United Kingdom",
            ".cn": "China",
            ".ru": "Russia",
            ".de": "Germany",
            ".fr": "France",
            ".jp": "Japan",
            ".au": "Australia",
            ".ca": "Canada",
            ".in": "India",
            "bbc.com": "United Kingdom",
            "reuters.com": "International",
            "apnews.com": "United States",
            "npr.org": "United States",
        }

        for suffix, origin in domain_origins.items():
            if domain.endswith(suffix):
                return origin

        # Check specific domains
        return domain_origins.get(domain)

    def _extract_author(self, content: str) -> Optional[str]:
        """Extract author name from content (basic pattern matching)."""
        # Common author patterns
        patterns = [
            r'[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
            r'[Aa]uthor:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
            r'[Ww]ritten\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)

        return None

    def _detect_article_type(self, content: str) -> str:
        """Detect article type based on content patterns."""
        content_lower = content[:500].lower()  # Check first 500 chars

        for type_name, pattern in self.type_patterns.items():
            if pattern.search(content_lower):
                return type_name

        return "article"  # Default type

    def _extract_categories_tags(self, content: str) -> Tuple[List[str], List[str]]:
        """Extract categories and tags from content patterns."""
        categories = []
        tags = []

        # Topic detection (extend patterns as needed)
        topic_patterns = {
            "technology": r'\b(?:AI|machine learning|software|hardware|tech|digital)\b',
            "politics": r'\b(?:election|government|policy|political|congress|parliament)\b',
            "business": r'\b(?:market|economy|finance|stock|trade|business|corporate)\b',
            "science": r'\b(?:research|study|scientist|discovery|experiment|data)\b',
            "health": r'\b(?:medical|health|disease|treatment|vaccine|hospital)\b',
        }

        content_lower = content.lower()
        for category, pattern in topic_patterns.items():
            if re.search(pattern, content_lower, re.IGNORECASE):
                categories.append(category)

        # Extract hashtag-like tags if present
        hashtags = re.findall(r'#\w+', content)
        tags.extend([tag[1:] for tag in hashtags[:10]])  # Limit to 10 tags

        return categories[:5], tags  # Limit categories to 5

    def _extract_html_metadata(self, html: str, metadata: ArticleMetadata):
        """Extract OpenGraph and Schema.org metadata from HTML."""
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # OpenGraph metadata
            og_title = soup.find('meta', property='og:title')
            if og_title:
                metadata.og_title = og_title.get('content')

            og_desc = soup.find('meta', property='og:description')
            if og_desc:
                metadata.og_description = og_desc.get('content')

            og_image = soup.find('meta', property='og:image')
            if og_image:
                metadata.og_image = og_image.get('content')

            # Schema.org metadata (JSON-LD)
            scripts = soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if '@type' in data:
                        metadata.schema_type = data['@type']

                        # Extract author from schema if available
                        if 'author' in data:
                            if isinstance(data['author'], dict):
                                metadata.author_name = data['author'].get('name')
                            elif isinstance(data['author'], str):
                                metadata.author_name = data['author']

                        # Extract published date from schema
                        if 'datePublished' in data and not metadata.published_date:
                            try:
                                metadata.published_date = datetime.fromisoformat(
                                    data['datePublished'].replace('Z', '+00:00')
                                )
                                metadata.content_age_hours = self._calculate_age_hours(
                                    metadata.published_date
                                )
                            except:
                                pass

                        break  # Use first valid schema found
                except json.JSONDecodeError:
                    continue

            # Additional author extraction from HTML
            if not metadata.author_name:
                author_elem = soup.find(class_=re.compile(r'author|byline', re.I))
                if author_elem:
                    metadata.author_name = author_elem.get_text(strip=True)

        except Exception as e:
            logger.warning(f"Failed to extract HTML metadata: {e}")