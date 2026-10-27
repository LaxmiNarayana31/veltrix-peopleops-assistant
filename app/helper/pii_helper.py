"""PII masking and sanitization helpers for employee records and response text."""

import logging
import re
from typing import Any, Dict, Optional

from app.exceptions.custom_exceptions import AppException, InternalServerException

logger = logging.getLogger(__name__)


class PiiHelper:
    """Class-level methods for masking emails, removing phone numbers, and scrubbing PII."""

    EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")
    PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")

    @classmethod
    def mask_email(cls, email: Optional[str]) -> str:
        """Mask email address as first char, ***, then domain (e.g., r***@veltrix.example)."""
        try:
            if not email or "@" not in email:
                return ""
            user, domain = email.split("@", 1)
            first_char = user[0] if user else ""
            return f"{first_char}***@{domain}"
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to mask email")
            raise InternalServerException("Email masking failed") from exc

    @classmethod
    def scrub_phones(cls, text: str) -> str:
        """Strip phone numbers completely from outgoing string."""
        try:
            if not text:
                return ""
            return cls.PHONE_PATTERN.sub("[PHONE_REMOVED]", text)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to scrub phone numbers")
            raise InternalServerException("Phone scrubbing failed") from exc

    @classmethod
    def scrub_text(cls, text: str) -> str:
        """Apply full PII scrubbing (mask emails and remove phones)."""
        try:
            if not text:
                return ""
            masked_text = cls.EMAIL_PATTERN.sub(r"\1***@\2", text)
            return cls.PHONE_PATTERN.sub("[PHONE_REMOVED]", masked_text)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to scrub text for PII")
            raise InternalServerException("PII scrubbing failed") from exc

    @classmethod
    def sanitize_employee_dict(cls, emp_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Produce safe copy of employee dictionary with phone stripped and email masked."""
        try:
            safe = dict(emp_dict)
            safe.pop("phone", None)
            if "email" in safe and safe["email"]:
                safe["email"] = cls.mask_email(safe["email"])
            return safe
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed sanitizing employee dict")
            raise InternalServerException("Dictionary sanitization failed") from exc


def get_pii_helper() -> PiiHelper:
    """Return PiiHelper instance for backward compatibility."""
    return PiiHelper()
