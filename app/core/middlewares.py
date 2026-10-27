import logging
import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware capturing request ID, employee ID header, and timing metrics."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Process incoming request, inject identifiers, and record elapsed latency."""
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        employee_id = request.headers.get("X-Employee-Id")

        request.state.request_id = request_id
        request.state.employee_id = employee_id

        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        response.headers["X-Request-Id"] = request_id

        logger.info(
            "Request finished: id=%s method=%s path=%s status=%d duration=%.2fms emp=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            employee_id or "anonymous",
        )
        return response
