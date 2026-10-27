"""JSON extraction and validation utilities for LLM payloads."""

import json
import logging
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from app.exceptions.custom_exceptions import AppException, ExtractionException

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class JsonUtils:
    """Robust extractor and parser for JSON payloads returned by LLMs."""

    @classmethod
    def extract_json_object(cls, text: str) -> Any:
        """Strip markdown fences and parse the first valid JSON array or object."""
        try:
            if not text:
                raise ExtractionException("Empty text cannot be parsed as JSON")

            # 1. Strip markdown fences if present
            cleaned = text.strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if fence_match:
                cleaned = fence_match.group(1).strip()

            # 2. Attempt direct parse
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

            # 3. Extract JSON object { ... } or array [ ... ]
            obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
            if obj_match:
                try:
                    return json.loads(obj_match.group(1))
                except json.JSONDecodeError:
                    pass

            # 4. Attempt minimal syntax fixes (replace unescaped newlines in strings)
            fixed = re.sub(r'(?<!\\)\n', r'\\n', cleaned)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError as exc:
                logger.warning("JSON parsing failed after cleanup: %s", exc)
                raise ExtractionException("Could not extract valid JSON from LLM response") from exc
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in extract_json_object")
            raise ExtractionException("JSON parsing encountered unexpected error") from exc

    @classmethod
    def parse_to_model(cls, text: str, model_cls: Type[T]) -> T:
        """Parse text to a validated Pydantic model instance."""
        try:
            raw_dict = cls.extract_json_object(text)
            if isinstance(raw_dict, list) and not issubclass(model_cls, list):
                if len(raw_dict) > 0 and isinstance(raw_dict[0], dict):
                    raw_dict = raw_dict[0]
            return model_cls.model_validate(raw_dict)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Validation of JSON against %s failed", model_cls.__name__)
            raise ExtractionException(f"Failed parsing LLM output to {model_cls.__name__}") from exc


def get_json_utils() -> JsonUtils:
    """Return JsonUtils instance for backward compatibility."""
    return JsonUtils()
