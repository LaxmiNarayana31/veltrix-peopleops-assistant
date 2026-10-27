"""FastAPI request dependencies resolving authentication and context."""

import logging
from typing import Optional

from fastapi import Header

from app.dto.chat_dto import RequestContext
from app.exceptions.custom_exceptions import AppException, UnauthorizedException
from app.helper.access.access_helper import AccessService

logger = logging.getLogger(__name__)


def get_current_user_context(x_employee_id: Optional[str] = Header(default=None, alias="X-Employee-Id")) -> RequestContext:
    """FastAPI dependency resolving RequestContext from X-Employee-Id header or raising 401."""
    try:
        return AccessService.authenticate_employee(x_employee_id)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Failed resolving user context from header")
        raise UnauthorizedException("Could not authenticate employee header") from exc
