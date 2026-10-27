"""Chat API endpoint exposing chat interaction route."""

import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_current_user_context
from app.dto.chat_dto import ChatRequest, ChatResponse, RequestContext
from app.exceptions.custom_exceptions import AppException, InternalServerException
from app.service.orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    chat_request: ChatRequest,
    request: Request,
    ctx: RequestContext = Depends(get_current_user_context),
) -> ChatResponse:
    """Handle chat interaction through the orchestrator service complying with API contract."""
    try:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        return await OrchestratorService.handle_chat(request_id, ctx, chat_request)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error processing chat endpoint for emp=%s", ctx.employee_id)
        raise InternalServerException("Could not process chat request") from exc
