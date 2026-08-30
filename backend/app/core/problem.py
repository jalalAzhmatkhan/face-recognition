"""RFC 9457 (problem+json) error handling.

Every error response body is an `application/problem+json` document:
{type, title, status, detail?, instance?, errors?}.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemError(Exception):
    """Domain error that maps directly to an RFC 9457 problem document."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type = type_
        self.extra = extra or {}
        super().__init__(title)


def problem_response(
    request: Request,
    status_code: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "instance": str(request.url.path),
    }
    if detail is not None:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_CONTENT_TYPE)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            request, exc.status_code, exc.title, exc.detail, exc.type, exc.extra
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return problem_response(
            request,
            exc.status_code,
            title=str(exc.detail) if exc.detail else "HTTP error",
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return problem_response(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation failed",
            detail="Request payload or parameters failed validation.",
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s", request.url.path)
        return problem_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal server error",
            detail="An unexpected error occurred.",
        )
