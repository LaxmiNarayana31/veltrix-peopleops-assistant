"""Token counter utility using tiktoken with cl100k_base encoding."""

import logging
from typing import Optional

import tiktoken

from app.exceptions.custom_exceptions import AppException, InternalServerException

logger = logging.getLogger(__name__)


class TokenCounter:
    """Class-level wrapper around tiktoken with cl100k_base encoding for accurate token counting."""

    _encoding: Optional[tiktoken.Encoding] = None

    @classmethod
    def get_encoding(cls) -> tiktoken.Encoding:
        """Lazy load and cache tiktoken encoding."""
        if cls._encoding is None:
            try:
                cls._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as exc:
                logger.exception("Failed initializing tiktoken with cl100k_base")
                raise InternalServerException("Could not initialize token counter") from exc
        return cls._encoding

    @classmethod
    def count_tokens(cls, text: Optional[str]) -> int:
        """Return exact token count for the input string."""
        try:
            if not text:
                return 0
            encoding = cls.get_encoding()
            return len(encoding.encode(text, disallowed_special=()))
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed counting tokens")
            raise InternalServerException("Token calculation failed") from exc

    @classmethod
    def truncate_to_tokens(cls, text: str, max_tokens: int) -> str:
        """Truncate input string to not exceed max_tokens."""
        try:
            if not text or max_tokens <= 0:
                return ""
            encoding = cls.get_encoding()
            tokens = encoding.encode(text, disallowed_special=())
            if len(tokens) <= max_tokens:
                return text
            return encoding.decode(tokens[:max_tokens])
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed truncating text to token limit %d", max_tokens)
            raise InternalServerException("Token truncation failed") from exc


def get_token_counter() -> TokenCounter:
    """Return TokenCounter class or instance for compatibility."""
    return TokenCounter()
