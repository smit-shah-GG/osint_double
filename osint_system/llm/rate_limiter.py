"""Token bucket rate limiter for API request throttling."""

import time
import threading
from typing import Optional

from loguru import logger


class TokenBucket:
    """
    Token bucket algorithm implementation for rate limiting.

    Tokens refill continuously at a fixed rate. Requests consume tokens.
    If insufficient tokens are available, the request must wait or be rejected.

    Attributes:
        capacity: Maximum number of tokens the bucket can hold
        refill_rate: Tokens added per second
        tokens: Current number of tokens available
        last_refill: Timestamp of last token refill
        lock: Thread lock for safe concurrent access
    """

    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket with capacity and refill rate.

        Args:
            capacity: Maximum tokens (e.g., 15 for 15 RPM)
            refill_rate: Tokens per second (e.g., 0.25 = 15 per minute)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self.lock = threading.Lock()

        logger.debug(
            f"TokenBucket initialized: capacity={capacity}, "
            f"refill_rate={refill_rate}/s"
        )

    def _refill(self) -> None:
        """
        Refill tokens based on time elapsed since last refill.

        Called internally before token acquisition to ensure bucket
        reflects current token count.
        """
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate tokens to add
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    def acquire(self, tokens: int = 1) -> bool:
        """
        Attempt to acquire tokens from the bucket (thread-safe).

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False if insufficient tokens available
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                logger.debug(f"Acquired {tokens} tokens, {self.tokens:.2f} remaining")
                return True

            logger.debug(f"Insufficient tokens: {self.tokens:.2f} < {tokens}")
            return False


class RateLimiter:
    """
    Multi-dimensional rate limiter using token buckets.

    Enforces both requests-per-minute (RPM) and tokens-per-minute (TPM)
    limits simultaneously to comply with API tier restrictions.

    Attributes:
        rpm_bucket: Token bucket for request rate limiting
        tpm_bucket: Token bucket for token rate limiting
    """

    def __init__(
        self,
        max_rpm: Optional[int] = None,
        max_tpm: Optional[int] = None
    ):
        """
        Initialize rate limiter with RPM and TPM constraints.

        Args:
            max_rpm: Maximum requests per minute (defaults to settings)
            max_tpm: Maximum tokens per minute (defaults to settings)
        """
        # Import here to avoid circular dependency
        from osint_system.config.settings import settings

        rpm = max_rpm or settings.max_rpm
        tpm = max_tpm or settings.max_tpm

        # RPM bucket: capacity = max_rpm, refill_rate = rpm/60 per second
        self.rpm_bucket = TokenBucket(
            capacity=rpm,
            refill_rate=rpm / 60.0
        )

        # TPM bucket: capacity = max_tpm, refill_rate = tpm/60 per second
        self.tpm_bucket = TokenBucket(
            capacity=tpm,
            refill_rate=tpm / 60.0
        )

        logger.info(
            f"RateLimiter initialized: {rpm} RPM, {tpm:,} TPM"
        )

    def can_proceed(self, token_count: int) -> bool:
        """
        Check if request can proceed given current rate limits.

        Attempts to acquire 1 request token (RPM) and token_count tokens (TPM).
        Only consumes tokens if BOTH buckets have sufficient capacity.

        Args:
            token_count: Number of tokens the request will consume

        Returns:
            True if request can proceed, False if rate limited
        """
        # Check both buckets without consuming tokens yet
        with self.rpm_bucket.lock:
            self.rpm_bucket._refill()
            rpm_available = self.rpm_bucket.tokens >= 1

        with self.tpm_bucket.lock:
            self.tpm_bucket._refill()
            tpm_available = self.tpm_bucket.tokens >= token_count

        if not rpm_available:
            logger.warning("RPM limit reached, request throttled")
            return False

        if not tpm_available:
            logger.warning(
                f"TPM limit reached, request throttled "
                f"(need {token_count}, have {self.tpm_bucket.tokens:.0f})"
            )
            return False

        # Both checks passed, consume tokens
        self.rpm_bucket.acquire(1)
        self.tpm_bucket.acquire(token_count)

        return True
