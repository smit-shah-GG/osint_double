"""Document crawler for PDF and web document extraction."""

from typing import Optional, Any
from datetime import datetime, timezone
from urllib.parse import urlparse
import asyncio

import httpx
import pypdfium2 as pdfium
import pdfplumber
import trafilatura
from trafilatura.metadata import extract_metadata
from loguru import logger

from osint_system.agents.crawlers.base_crawler import BaseCrawler


class DocumentCrawler(BaseCrawler):
    """
    Crawler specialized for PDF and web document extraction.

    Uses pypdfium2 for high-quality PDF text extraction, falling back to
    pdfplumber for table-heavy documents. Web content extraction uses
    trafilatura (F1 score 0.958) with fallback strategies.

    Implements quality filtering based on content length and authority scoring
    based on domain type (government/edu = 0.9, org = 0.7, others = 0.5).

    Attributes:
        client: Shared httpx.AsyncClient for document fetching
        min_content_length: Minimum content length to consider valid (default 500)
        timeout: HTTP request timeout in seconds
    """

    # Domain authority scores based on source type
    AUTHORITY_DOMAINS = {
        # Government domains (highest authority)
        ".gov": 0.9,
        ".gov.uk": 0.9,
        ".mil": 0.9,
        # Educational domains
        ".edu": 0.9,
        ".ac.uk": 0.9,
        # Organizational domains
        ".org": 0.7,
        # Major credible news sources
        "reuters.com": 0.85,
        "apnews.com": 0.85,
        "bbc.com": 0.8,
        "nytimes.com": 0.8,
        "theguardian.com": 0.8,
    }

    def __init__(
        self,
        name: str = "DocumentCrawler",
        description: str = "PDF and web document extraction crawler",
        min_content_length: int = 500,
        timeout: float = 30.0,
        mcp_enabled: bool = False,
        mcp_server_command: Optional[list[str]] = None,
    ):
        """
        Initialize document crawler.

        Args:
            name: Crawler name for identification
            description: Description of crawler purpose
            min_content_length: Minimum content length to consider valid
            timeout: HTTP request timeout in seconds
            mcp_enabled: Whether to enable MCP client
            mcp_server_command: Command to start MCP server
        """
        super().__init__(
            name=name,
            description=description,
            mcp_enabled=mcp_enabled,
            mcp_server_command=mcp_server_command,
        )
        self.min_content_length = min_content_length
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self.logger = logger.bind(module="DocumentCrawler")

        self.logger.info(
            "DocumentCrawler initialized",
            min_content_length=min_content_length,
            timeout=timeout,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_connections=50),
                follow_redirects=True,
                headers={
                    "User-Agent": "OSINT-DocumentCrawler/1.0 (Research; +https://github.com/smit-shah-GG/osint_double)"
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def is_pdf(self, url: str, content_type: Optional[str] = None) -> bool:
        """
        Determine if URL points to a PDF document.

        Checks both URL extension and content-type header if available.

        Args:
            url: URL to check
            content_type: Optional content-type header value

        Returns:
            True if URL points to PDF, False otherwise
        """
        # Check URL extension
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        if path_lower.endswith(".pdf"):
            return True

        # Check content-type header if provided
        if content_type:
            return "application/pdf" in content_type.lower()

        return False

    async def fetch_document(self, url: str) -> dict:
        """
        Fetch document from URL.

        Downloads the document content and determines its type based on
        content-type header and URL extension.

        Args:
            url: URL of document to fetch

        Returns:
            Dictionary containing:
            - success: bool indicating fetch success
            - content: Raw bytes for PDF, text for HTML
            - content_type: Detected content type
            - url: Original URL
            - error: Error message if failed

        Raises:
            Does not raise - errors returned in result dict
        """
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            is_pdf = self.is_pdf(url, content_type)

            return {
                "success": True,
                "content": response.content if is_pdf else response.text,
                "content_type": "pdf" if is_pdf else "html",
                "url": url,
                "error": None,
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error {e.response.status_code}: {e}"
            self.logger.warning(error_msg, url=url)
            return {
                "success": False,
                "content": None,
                "content_type": None,
                "url": url,
                "error": error_msg,
            }

        except httpx.RequestError as e:
            error_msg = f"Request failed: {e}"
            self.logger.warning(error_msg, url=url)
            return {
                "success": False,
                "content": None,
                "content_type": None,
                "url": url,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            self.logger.error(error_msg, url=url, exc_info=True)
            return {
                "success": False,
                "content": None,
                "content_type": None,
                "url": url,
                "error": error_msg,
            }

    def extract_pdf_content(self, pdf_bytes: bytes) -> dict:
        """
        Extract text content from PDF bytes.

        Uses pypdfium2 as primary extractor for best text quality.
        Falls back to pdfplumber for table extraction if pypdfium2
        yields sparse results.

        Args:
            pdf_bytes: Raw PDF file bytes

        Returns:
            Dictionary containing:
            - success: bool indicating extraction success
            - text: Extracted text content
            - page_count: Number of pages in PDF
            - extractor: Which extractor was used
            - error: Error message if failed
        """
        text_parts = []
        page_count = 0

        # Try pypdfium2 first (best quality)
        try:
            pdf = pdfium.PdfDocument(pdf_bytes)
            page_count = len(pdf)

            for page in pdf:
                text_page = page.get_textpage()
                page_text = text_page.get_text_range()
                if page_text:
                    text_parts.append(page_text)
                page.close()

            pdf.close()

            combined_text = "\n\n".join(text_parts)

            # If pypdfium2 yielded good results, return them
            if combined_text and len(combined_text.strip()) >= self.min_content_length:
                self.logger.debug(
                    "PDF extracted with pypdfium2",
                    page_count=page_count,
                    text_length=len(combined_text),
                )
                return {
                    "success": True,
                    "text": combined_text,
                    "page_count": page_count,
                    "extractor": "pypdfium2",
                    "error": None,
                }

        except Exception as e:
            self.logger.debug(f"pypdfium2 extraction failed: {e}, trying pdfplumber")

        # Fallback to pdfplumber (better for tables)
        try:
            import io
            text_parts = []

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

                    # Also extract tables if present
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            table_text = "\n".join(
                                "\t".join(str(cell) if cell else "" for cell in row)
                                for row in table
                            )
                            text_parts.append(table_text)

            combined_text = "\n\n".join(text_parts)

            if combined_text:
                self.logger.debug(
                    "PDF extracted with pdfplumber fallback",
                    page_count=page_count,
                    text_length=len(combined_text),
                )
                return {
                    "success": True,
                    "text": combined_text,
                    "page_count": page_count,
                    "extractor": "pdfplumber",
                    "error": None,
                }

        except Exception as e:
            error_msg = f"PDF extraction failed with all extractors: {e}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "text": "",
                "page_count": page_count,
                "extractor": None,
                "error": error_msg,
            }

        return {
            "success": False,
            "text": "",
            "page_count": page_count,
            "extractor": None,
            "error": "No extractable text found in PDF",
        }

    def calculate_authority_score(self, url: str) -> float:
        """
        Calculate authority score for a URL based on domain type.

        Government and educational domains receive highest scores.
        Organizational domains receive medium scores.
        All other domains receive default score.

        Args:
            url: URL to score

        Returns:
            Authority score between 0.0 and 1.0
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Check for exact domain matches first (e.g., reuters.com)
        for known_domain, score in self.AUTHORITY_DOMAINS.items():
            if not known_domain.startswith("."):
                if domain == known_domain or domain.endswith("." + known_domain):
                    self.logger.debug(
                        f"Authority score matched: {known_domain}",
                        url=url,
                        score=score,
                    )
                    return score

        # Check for TLD-based matches (e.g., .gov, .edu)
        for tld, score in self.AUTHORITY_DOMAINS.items():
            if tld.startswith("."):
                if domain.endswith(tld):
                    self.logger.debug(
                        f"Authority score matched TLD: {tld}",
                        url=url,
                        score=score,
                    )
                    return score

        # Default score for unknown domains
        return 0.5

    def extract_with_fallback(self, html: str, url: str) -> Optional[str]:
        """
        Extract content with fallback chain.

        Follows Pattern 3 from research: try trafilatura first,
        fallback to BeautifulSoup raw text extraction if needed.

        Args:
            html: Raw HTML content
            url: Source URL for context

        Returns:
            Extracted text content or None if all extractors fail
        """
        # Try trafilatura first (best F1 scores)
        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            target_language="en",
            favor_precision=True,
        )

        if content and len(content.strip()) >= self.min_content_length:
            self.logger.debug(
                "Content extracted with trafilatura",
                url=url,
                length=len(content),
            )
            return content

        # Fallback to trafilatura with lower precision (catches more content)
        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )

        if content and len(content.strip()) >= self.min_content_length:
            self.logger.debug(
                "Content extracted with trafilatura (recall mode)",
                url=url,
                length=len(content),
            )
            return content

        # Final fallback: BeautifulSoup raw text
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer"]):
                script.decompose()

            # Get text
            text = soup.get_text(separator="\n", strip=True)

            if text and len(text.strip()) >= self.min_content_length:
                self.logger.debug(
                    "Content extracted with BeautifulSoup fallback",
                    url=url,
                    length=len(text),
                )
                return text

        except Exception as e:
            self.logger.debug(f"BeautifulSoup fallback failed: {e}")

        self.logger.warning(
            "All content extractors failed or returned insufficient content",
            url=url,
        )
        return None

    def extract_web_content(self, html: str, url: str) -> dict:
        """
        Extract main content from HTML using trafilatura with fallback.

        Uses trafilatura for high-quality content extraction with
        table support enabled. Falls back to BeautifulSoup if needed.

        Args:
            html: Raw HTML content
            url: Source URL for metadata extraction

        Returns:
            Dictionary containing:
            - success: bool indicating extraction success
            - text: Extracted main content
            - title: Document title
            - author: Document author
            - date: Publication date
            - error: Error message if failed
        """
        try:
            # Extract metadata first (always attempt)
            metadata = extract_metadata(html)

            title = metadata.title if metadata else None
            author = metadata.author if metadata else None
            date = metadata.date if metadata else None

            # Extract content with fallback chain
            content = self.extract_with_fallback(html, url)

            if content:
                self.logger.debug(
                    "Web content extracted successfully",
                    url=url,
                    content_length=len(content),
                    has_title=title is not None,
                )
                return {
                    "success": True,
                    "text": content,
                    "title": title,
                    "author": author,
                    "date": date,
                    "error": None,
                }

            return {
                "success": False,
                "text": "",
                "title": title,
                "author": author,
                "date": date,
                "error": "No extractable content found (all fallbacks failed)",
            }

        except Exception as e:
            error_msg = f"Web content extraction failed: {e}"
            self.logger.error(error_msg, url=url)
            return {
                "success": False,
                "text": "",
                "title": None,
                "author": None,
                "date": None,
                "error": error_msg,
            }

    async def process_document(self, url: str) -> Optional[dict]:
        """
        Process a document URL and extract content with metadata.

        Routes to appropriate extractor based on document type.
        Returns structured result with content, metadata, and quality scores.
        Applies quality filtering: returns None for low-quality content.

        Args:
            url: URL of document to process

        Returns:
            Dictionary containing:
            - success: bool indicating overall success
            - content: Extracted text content
            - document_type: 'pdf' or 'web'
            - metadata: Dict with title, author, date, page_count, authority_score
            - source_url: Original URL
            - retrieved_at: ISO timestamp of retrieval
            - error: Error message if failed

            Returns None if content does not meet quality thresholds
            (length < min_content_length).
        """
        self.logger.info(f"Processing document: {url}")

        # Calculate authority score upfront
        authority_score = self.calculate_authority_score(url)

        # Fetch document
        fetch_result = await self.fetch_document(url)
        if not fetch_result["success"]:
            return {
                "success": False,
                "content": "",
                "document_type": None,
                "metadata": {"authority_score": authority_score},
                "source_url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "error": fetch_result["error"],
            }

        # Extract based on type
        if fetch_result["content_type"] == "pdf":
            extraction = self.extract_pdf_content(fetch_result["content"])
            if not extraction["success"]:
                return {
                    "success": False,
                    "content": "",
                    "document_type": "pdf",
                    "metadata": {
                        "page_count": extraction.get("page_count", 0),
                        "authority_score": authority_score,
                    },
                    "source_url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "error": extraction["error"],
                }

            # Quality filter: check minimum content length
            if len(extraction["text"].strip()) < self.min_content_length:
                self.logger.info(
                    "PDF content below minimum length threshold",
                    url=url,
                    content_length=len(extraction["text"]),
                    min_required=self.min_content_length,
                )
                return None

            return {
                "success": True,
                "content": extraction["text"],
                "document_type": "pdf",
                "metadata": {
                    "page_count": extraction["page_count"],
                    "extractor": extraction["extractor"],
                    "authority_score": authority_score,
                },
                "source_url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }

        else:  # HTML/web content
            extraction = self.extract_web_content(fetch_result["content"], url)
            if not extraction["success"]:
                return {
                    "success": False,
                    "content": "",
                    "document_type": "web",
                    "metadata": {"authority_score": authority_score},
                    "source_url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "error": extraction["error"],
                }

            # Quality filter: check minimum content length
            if len(extraction["text"].strip()) < self.min_content_length:
                self.logger.info(
                    "Web content below minimum length threshold",
                    url=url,
                    content_length=len(extraction["text"]),
                    min_required=self.min_content_length,
                )
                return None

            return {
                "success": True,
                "content": extraction["text"],
                "document_type": "web",
                "metadata": {
                    "title": extraction["title"],
                    "author": extraction["author"],
                    "date": extraction["date"],
                    "authority_score": authority_score,
                },
                "source_url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }

    # BaseCrawler abstract method implementations

    async def fetch_data(self, source: str, **kwargs) -> dict:
        """
        Fetch and extract data from a document source.

        Implementation of BaseCrawler abstract method.

        Args:
            source: Document URL to fetch
            **kwargs: Additional parameters (unused)

        Returns:
            Dictionary containing extracted document data
        """
        result = await self.process_document(source)
        if result is None:
            return {
                "success": False,
                "error": "Content did not meet quality thresholds",
                "source": source,
            }
        return result

    async def filter_relevance(self, data: dict) -> bool:
        """
        Check if extracted document is relevant.

        Implementation of BaseCrawler abstract method.
        Checks content length meets minimum threshold.

        Args:
            data: Extracted document data

        Returns:
            True if document is relevant, False otherwise
        """
        if not data.get("success"):
            return False

        content = data.get("content", "")
        return len(content) >= self.min_content_length

    async def extract_metadata(self, data: dict) -> dict:
        """
        Extract standardized metadata from document.

        Implementation of BaseCrawler abstract method.

        Args:
            data: Extracted document data

        Returns:
            Standardized metadata dictionary including authority_score
        """
        return {
            "source_url": data.get("source_url"),
            "document_type": data.get("document_type"),
            "title": data.get("metadata", {}).get("title"),
            "author": data.get("metadata", {}).get("author"),
            "publication_date": data.get("metadata", {}).get("date"),
            "retrieved_at": data.get("retrieved_at"),
            "page_count": data.get("metadata", {}).get("page_count"),
            "authority_score": data.get("metadata", {}).get("authority_score"),
        }

    async def process(self, input_data: dict) -> dict:
        """
        Process input data and return results.

        Implementation of BaseAgent abstract method.
        Delegates to fetch_data for document processing.

        Args:
            input_data: Dictionary containing 'url' or 'source' key

        Returns:
            Dictionary containing processing results and status
        """
        url = input_data.get("url") or input_data.get("source")
        if not url:
            return {
                "success": False,
                "error": "No URL provided in input_data (expected 'url' or 'source' key)",
            }

        return await self.fetch_data(url)

    def get_capabilities(self) -> list[str]:
        """Return document crawler capabilities."""
        return [
            "data_acquisition",
            "source_crawling",
            "metadata_extraction",
            "pdf_extraction",
            "web_content_extraction",
        ]
