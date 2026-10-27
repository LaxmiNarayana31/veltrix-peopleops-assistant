"""Injection and safety guard evaluating user prompts against heuristic attack patterns."""

import logging
import re
from typing import Optional, Tuple

from app.exceptions.custom_exceptions import AppException
from app.utils.constants import (
    BULK_REQUEST_REFUSAL_MESSAGE,
    INJECTION_REFUSAL_MESSAGE,
    OFF_TOPIC_REFUSAL_MESSAGE,
    ChatRoute,
)

logger = logging.getLogger(__name__)


class InjectionGuard:
    """Detects prompt manipulation, bulk-data queries, role claims, and off-topic prompts."""

    # Heuristic patterns for instruction manipulation or prompt extraction
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
        re.compile(r"system\s+prompt", re.IGNORECASE),
        re.compile(r"developer\s+mode", re.IGNORECASE),
        re.compile(r"jailbreak", re.IGNORECASE),
        re.compile(r"disregard\s+(?:the\s+)?rules", re.IGNORECASE),
        re.compile(r"what\s+are\s+your\s+(?:hidden\s+)?instructions", re.IGNORECASE),
        re.compile(r"reveal\s+(?:your\s+)?prompt", re.IGNORECASE),
        re.compile(r"i\s+am\s+(?:the\s+)?(?:hr\s+director|ceo|admin|superadmin)", re.IGNORECASE),
        re.compile(r"treat\s+me\s+as\s+(?:hr|admin|manager)", re.IGNORECASE),
        re.compile(r"i(?:'m|\s+am)\s+in\s+the\s+(?:us|germany|india|berlin|austin)\s+office", re.IGNORECASE),
    ]

    # Bulk employee data query patterns
    BULK_PATTERNS = [
        re.compile(r"(?:show|list|get|export|dump)(?:\s+me)?\s+(?:all|everyone'?s?|every)\s+(?:employee|leave|balance)", re.IGNORECASE),
        re.compile(r"(?:everyone'?s?|all\s+employees'?)\s+(?:leave\s+)?balances?", re.IGNORECASE),
        re.compile(r"(?:balances|leaves)\s+(?:of|for)\s+(?:all|everyone|every\s+employee)", re.IGNORECASE),
        re.compile(r"dump\s+(?:the\s+)?(?:database|employees|leave_balances)", re.IGNORECASE),
    ]

    # Off-topic requests (coding, math, creative writing)
    OFF_TOPIC_PATTERNS = [
        re.compile(r"(?:write|generate|debug)\s+(?:a\s+)?(?:python|javascript|code|script|sql\s+query)", re.IGNORECASE),
        re.compile(r"what\s+is\s+the\s+capital\s+of", re.IGNORECASE),
        re.compile(r"solve\s+(?:the\s+)?equation", re.IGNORECASE),
    ]

    @classmethod
    def evaluate(cls, message: str) -> Optional[Tuple[ChatRoute, str]]:
        """Evaluate user message against security heuristics.

        Returns:
            Tuple of (ChatRoute.REFUSE, refusal_message) if violation detected, or None if safe.
        """
        try:
            # Bulk data query check
            for pattern in cls.BULK_PATTERNS:
                if pattern.search(message):
                    logger.warning("Bulk data query detected and blocked")
                    return ChatRoute.REFUSE, BULK_REQUEST_REFUSAL_MESSAGE

            # Prompt injection and role spoofing check
            for pattern in cls.INJECTION_PATTERNS:
                if pattern.search(message):
                    logger.warning("Prompt injection / role spoofing pattern detected and blocked")
                    return ChatRoute.REFUSE, INJECTION_REFUSAL_MESSAGE

            # Off-topic check
            for pattern in cls.OFF_TOPIC_PATTERNS:
                if pattern.search(message):
                    logger.info("Off-topic prompt detected and politely refused")
                    return ChatRoute.REFUSE, OFF_TOPIC_REFUSAL_MESSAGE

            return None
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Injection guard evaluation failed")
            return None


def get_injection_guard() -> InjectionGuard:
    """Return InjectionGuard instance for backward compatibility."""
    return InjectionGuard()
