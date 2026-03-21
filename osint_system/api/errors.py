"""RFC 7807 Problem Details error handling for the API layer.

Provides a base ``ProblemDetailError`` exception and convenience subclasses
for common HTTP error codes.  ``register_error_handlers`` installs three
FastAPI exception handlers that render all errors as
``application/problem+json`` responses per RFC 7807.

The ``fastapi-rfc7807`` library is abandoned (last release 2021, Python 3.6-3.9
only), so these handlers are a minimal, modern replacement.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ProblemDetailError(Exception):
    """Base exception for RFC 7807 problem detail responses.

    Raise from route handlers to return a structured error with the
    ``application/problem+json`` media type.

    Attributes:
        status: HTTP status code.
        title: Short human-readable summary.
        detail: Longer human-readable explanation.
        type_uri: Error type URI (defaults to ``about:blank``).
        instance: URI identifying the specific occurrence (populated by
            the handler if not set explicitly).
    """

    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        type_uri: str = "about:blank",
        instance: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.type_uri = type_uri
        self.instance = instance


class NotFoundError(ProblemDetailError):
    """Convenience 404 Not Found error."""

    def __init__(
        self,
        detail: str = "The requested resource was not found.",
        instance: str | None = None,
    ) -> None:
        super().__init__(
            status=404,
            title="Not Found",
            detail=detail,
            instance=instance,
        )


class ConflictError(ProblemDetailError):
    """Convenience 409 Conflict error.

    Used for invalid investigation status transitions (e.g. COMPLETED -> RUNNING).
    """

    def __init__(
        self,
        detail: str = "The request conflicts with the current resource state.",
        instance: str | None = None,
    ) -> None:
        super().__init__(
            status=409,
            title="Conflict",
            detail=detail,
            instance=instance,
        )


def register_error_handlers(app: FastAPI) -> None:
    """Register RFC 7807 compliant exception handlers on *app*.

    Installs handlers for:
    - ``ProblemDetailError``: custom application errors.
    - ``HTTPException``: Starlette/FastAPI HTTP errors.
    - ``RequestValidationError``: Pydantic validation failures (422).

    All responses use ``media_type="application/problem+json"`` and include
    the ``instance`` field set to ``str(request.url)`` per CONTEXT.md.
    """

    @app.exception_handler(ProblemDetailError)
    async def _problem_detail_handler(
        request: Request, exc: ProblemDetailError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "type": exc.type_uri,
                "title": exc.title,
                "status": exc.status,
                "detail": exc.detail,
                "instance": exc.instance or str(request.url),
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": exc.detail,
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": str(request.url),
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "detail": str(exc.errors()),
                "instance": str(request.url),
            },
            media_type="application/problem+json",
        )
