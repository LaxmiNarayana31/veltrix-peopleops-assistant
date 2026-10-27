import logging
import os
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from google import genai
from google.genai import types
import groq
from pydantic import BaseModel

from app.exceptions.custom_exceptions import (
    AppException,
    ConfigurationException,
    LlmProviderException,
    RateLimitException,
    TokenBudgetExceededException,
)
from app.utils.token_counter import TokenCounter
from config.app_config import (
    CORPUS_TOKEN_BUDGET,
    GEMINI_PRIMARY_MODEL,
    GROQ_PRIMARY_MODEL,
    LLM_FALLBACK_CHAIN,
    REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM API providers."""

    @abstractmethod
    def generate_json(
        self,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 2000,
    ) -> str:
        """Generate structured JSON response adhering to schema."""
        pass

    @abstractmethod
    def generate_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """Generate plain text response."""
        pass

    @property
    def model_name(self) -> str:
        """Return model name identifier."""
        return getattr(self, "_model_name", "")


class GeminiProvider(BaseLLMProvider):
    """Provider for Google Gemini and Gemma models via google-genai SDK."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        """Initialize provider with model name."""
        self._model_name = model_name or GEMINI_PRIMARY_MODEL

    @property
    def model_name(self) -> str:
        return self._model_name

    def _is_gemma(self) -> bool:
        """Check if active model is a Gemma variant."""
        return "gemma" in self.model_name.lower()

    def generate_json(
        self,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 2000,
    ) -> str:
        """Call Gemini/Gemma API enforcing structured JSON format and temperature 0."""
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ConfigurationException("GEMINI_API_KEY or GOOGLE_API_KEY is not configured")

            client = genai.Client(api_key=api_key)

            if self._is_gemma():
                prompt_content = f"{system}\n\nTask:\n{user}"
                config = types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                )
            else:
                prompt_content = user
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.0,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                )

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt_content,
                config=config,
            )
            return response.text or "{}"
        except AppException:
            raise
        except Exception as exc:
            logger.warning("GeminiProvider (%s) call failed: %s", self.model_name, exc)
            if "429" in str(exc) or "quota" in str(exc).lower():
                raise RateLimitException("Gemini quota or rate limit exceeded") from exc
            raise LlmProviderException(f"Gemini API failure on {self.model_name}") from exc

    def generate_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """Call Gemini/Gemma API generating plain text at temperature 0."""
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ConfigurationException("GEMINI_API_KEY or GOOGLE_API_KEY is not configured")

            client = genai.Client(api_key=api_key)

            if self._is_gemma():
                prompt_content = f"{system}\n\nTask:\n{user}"
                config = types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=max_tokens,
                )
            else:
                prompt_content = user
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.0,
                    max_output_tokens=max_tokens,
                )

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt_content,
                config=config,
            )
            return response.text or ""
        except AppException:
            raise
        except Exception as exc:
            logger.warning("GeminiProvider (%s) text call failed: %s", self.model_name, exc)
            if "429" in str(exc) or "quota" in str(exc).lower():
                raise RateLimitException("Gemini quota or rate limit exceeded") from exc
            raise LlmProviderException(f"Gemini API failure on {self.model_name}") from exc


class GroqProvider(BaseLLMProvider):
    """Provider for Groq Cloud models with JSON mode and fallback support."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        """Initialize Groq provider with model name."""
        self._model_name = model_name or GROQ_PRIMARY_MODEL

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate_json(
        self,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 2000,
    ) -> str:
        """Execute Groq JSON completion at temperature 0."""
        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ConfigurationException("GROQ_API_KEY is not configured")

            client = groq.Groq(api_key=api_key)
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or "{}"
        except AppException:
            raise
        except Exception as exc:
            logger.warning("GroqProvider (%s) call failed: %s", self.model_name, exc)
            if "429" in str(exc) or "rate" in str(exc).lower():
                raise RateLimitException("Groq rate limit exceeded") from exc
            raise LlmProviderException(f"Groq API failure on {self.model_name}") from exc

    def generate_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """Execute Groq text completion at temperature 0."""
        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ConfigurationException("GROQ_API_KEY is not configured")

            client = groq.Groq(api_key=api_key)
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except AppException:
            raise
        except Exception as exc:
            logger.warning("GroqProvider (%s) text call failed: %s", self.model_name, exc)
            if "429" in str(exc) or "rate" in str(exc).lower():
                raise RateLimitException("Groq rate limit exceeded") from exc
            raise LlmProviderException(f"Groq API failure on {self.model_name}") from exc


class LlmGateway:
    """Central gateway enforcing the corpus token budget, fallback execution, and audit logging."""

    _custom_provider: Optional[BaseLLMProvider] = None

    @classmethod
    def set_provider(cls, provider: BaseLLMProvider) -> None:
        """Inject a custom LLM provider (used in automated tests)."""
        cls._custom_provider = provider

    @classmethod
    def call(
        cls,
        system: str,
        user: str,
        call_purpose: str,
        request_id: str,
        corpus_text: str = "",
        is_json: bool = True,
        schema: Optional[Type[BaseModel]] = None,
    ) -> str:
        """Execute LLM call enforcing the 3,000 corpus token limit and fallback chain."""
        try:
            corpus_tokens = TokenCounter.count_tokens(corpus_text)
            if corpus_tokens > CORPUS_TOKEN_BUDGET:
                logger.error(
                    "TokenBudgetExceeded in gateway: id=%s purpose=%s tokens=%d > %d",
                    request_id,
                    call_purpose,
                    corpus_tokens,
                    CORPUS_TOKEN_BUDGET,
                )
                raise TokenBudgetExceededException(
                    f"Corpus token count ({corpus_tokens}) exceeds maximum allowed budget of {CORPUS_TOKEN_BUDGET}"
                )

            if cls._custom_provider is not None:
                start_time = time.perf_counter()
                if hasattr(cls._custom_provider, "active_purpose"):
                    cls._custom_provider.active_purpose = call_purpose
                if is_json:
                    result = cls._custom_provider.generate_json(system, user, schema)
                else:
                    result = cls._custom_provider.generate_text(system, user)
                latency_ms = (time.perf_counter() - start_time) * 1000

                logger.info(
                    "LLM gateway call: request_id=%s purpose=%s provider=test_custom model=injected corpus_tokens=%d latency_ms=%.2f",
                    request_id,
                    call_purpose,
                    corpus_tokens,
                    latency_ms,
                )
                return result

            last_exception: Optional[Exception] = None
            total_start_time = time.perf_counter()

            for provider_key, model_name in LLM_FALLBACK_CHAIN:
                if time.perf_counter() - total_start_time > REQUEST_TIMEOUT_SECONDS:
                    raise LlmProviderException("Request deadline exceeded during provider fallback")

                provider_instance: BaseLLMProvider
                if provider_key in ("gemini", "gemma"):
                    provider_instance = GeminiProvider(model_name)
                elif provider_key == "groq":
                    provider_instance = GroqProvider(model_name)
                else:
                    continue

                call_start = time.perf_counter()
                try:
                    if is_json:
                        output = provider_instance.generate_json(system, user, schema)
                    else:
                        output = provider_instance.generate_text(system, user)

                    latency_ms = (time.perf_counter() - call_start) * 1000
                    logger.info(
                        "LLM gateway call: request_id=%s purpose=%s provider=%s model=%s corpus_tokens=%d latency_ms=%.2f",
                        request_id,
                        call_purpose,
                        provider_key,
                        model_name,
                        corpus_tokens,
                        latency_ms,
                    )
                    return output
                except (RateLimitException, LlmProviderException, ConfigurationException) as exc:
                    logger.warning("Provider %s (%s) failed for %s, trying next fallback: %s", provider_key, model_name, call_purpose, exc)
                    last_exception = exc
                    time.sleep(0.5 + random.uniform(0.1, 0.4))
                except Exception as exc:
                    logger.exception("Unexpected error in provider %s (%s)", provider_key, model_name)
                    last_exception = exc

            logger.error("All providers in fallback chain exhausted for request %s", request_id)
            if last_exception:
                raise last_exception
            raise LlmProviderException("All fallback LLM providers failed")
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Fatal exception in LLM gateway for %s", request_id)
            raise LlmProviderException("LLM gateway execution failed") from exc

    execute_call = call


# Module-level singleton
_llm_gateway: Optional[LlmGateway] = None


class FakeLLMProvider(BaseLLMProvider):
    """Deterministic fake LLM provider for testing."""

    def __init__(self) -> None:
        self._responses: Dict[str, str] = {}
        self.active_purpose: Optional[str] = None
        self._default_response: str = "{}"

    def set_response(self, key: str, response: str) -> None:
        self._responses[key] = response

    @property
    def model_name(self) -> str:
        return "fake-llm-model"

    def generate_json(
        self,
        system: str,
        user: str,
        schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 2000,
    ) -> str:
        if self.active_purpose and self.active_purpose in self._responses:
            return self._responses[self.active_purpose]
        for k, v in self._responses.items():
            if k in user or k in system:
                return v
        return self._default_response

    def generate_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        if self.active_purpose and self.active_purpose in self._responses:
            return self._responses[self.active_purpose]
        for k, v in self._responses.items():
            if k in user or k in system:
                return v
        return "Fake LLM answer."


def get_llm_gateway() -> LlmGateway:
    """Return singleton LlmGateway instance."""
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LlmGateway()
    return _llm_gateway

# Aliases for helper usage
LlmHelper = LlmGateway
get_llm_helper = get_llm_gateway

