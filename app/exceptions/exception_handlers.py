import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.status_codes import ErrorCode, StatusCode
from app.exceptions.custom_exceptions import AppException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application instance."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Override FastAPI default 422 validation error with 400 Bad Request."""
        logger.warning("Request validation failed on path %s: %s", request.url.path, str(exc))
        return JSONResponse(
            status_code=StatusCode.BAD_REQUEST,
            content={
                "detail": "Invalid request payload or parameters",
                "error_code": ErrorCode.BAD_REQUEST.value,
            },
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """Handle domain AppException hierarchy."""
        logger.warning(
            "AppException handled on path %s: status=%d code=%s msg=%s",
            request.url.path,
            exc.status_code,
            exc.error_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error_code": exc.error_code.value if hasattr(exc.error_code, "value") else str(exc.error_code),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Handle Starlette/FastAPI built-in HTTP exceptions."""
        logger.warning("HTTPException on %s: status=%d detail=%s", request.url.path, exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": str(exc.detail),
                "error_code": ErrorCode.BAD_REQUEST.value if exc.status_code == 400 else ErrorCode.INTERNAL_SERVER_ERROR.value,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle any unexpected unhandled exceptions without leaking internal details."""
        logger.exception("Unhandled server exception on %s", request.url.path)
        return JSONResponse(
            status_code=StatusCode.INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal server error occurred",
                "error_code": ErrorCode.INTERNAL_SERVER_ERROR.value,
            },
        )
