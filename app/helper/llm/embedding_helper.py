import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from abc import ABC, abstractmethod
from typing import List, Optional

from google import genai
from google.genai import types

from app.exceptions.custom_exceptions import AppException, ConfigurationException, LlmProviderException
from config.app_config import EMBEDDING_CACHE_DB_PATH, GEMINI_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class BaseEmbeddingService(ABC):
    """Abstract base interface for text embedding models."""

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for a collection of document texts."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Generate vector embedding for a search query string."""
        pass


class GeminiEmbeddingService(BaseEmbeddingService):
    """Production Gemini embedding service with persistent SQLite caching and exponential retry backoff."""

    def __init__(self, cache_db_path: Optional[str] = None, dimension: int = 768) -> None:
        """Initialize embedding service, cache store, and configuration."""
        self.model_name = GEMINI_EMBEDDING_MODEL
        self.dimension = dimension
        self.cache_db_path = cache_db_path or EMBEDDING_CACHE_DB_PATH
        self._init_cache_db()

    def _init_cache_db(self) -> None:
        """Initialize SQLite table for caching generated embedding vectors."""
        Path(self.cache_db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    text_hash TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _get_cached_embedding(self, text_hash: str) -> Optional[List[float]]:
        """Retrieve precomputed embedding vector from cache by text SHA-256."""
        with sqlite3.connect(self.cache_db_path) as conn:
            row = conn.execute(
                "SELECT embedding_json FROM embedding_cache WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _save_cached_embeddings(self, pairs: List[tuple[str, List[float]]]) -> None:
        """Save a batch of computed embeddings to SQLite cache."""
        if not pairs:
            return
        with sqlite3.connect(self.cache_db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO embedding_cache (text_hash, embedding_json) VALUES (?, ?)",
                [(th, json.dumps(vec)) for th, vec in pairs],
            )
            conn.commit()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for document chunks in batches with caching and retry backoff."""
        try:
            if not texts:
                return []

            gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not gemini_api_key:
                logger.error("Attempted to embed documents without GEMINI_API_KEY or GOOGLE_API_KEY")
                raise ConfigurationException("GEMINI_API_KEY or GOOGLE_API_KEY is not configured")

            client = genai.Client(api_key=gemini_api_key)
            results: List[Optional[List[float]]] = [None] * len(texts)
            missing_indices: List[int] = []
            hashes: List[str] = []

            for i, text in enumerate(texts):
                th = hashlib.sha256(text.encode("utf-8")).hexdigest()
                hashes.append(th)
                cached = self._get_cached_embedding(th)
                if cached is not None:
                    results[i] = cached
                else:
                    missing_indices.append(i)

            logger.info(
                "Embedding %d chunks (cache hits=%d, API calls needed=%d) using %s",
                len(texts),
                len(texts) - len(missing_indices),
                len(missing_indices),
                self.model_name,
            )

            if not missing_indices:
                return [r for r in results if r is not None]

            batch_size = 100
            to_cache: List[tuple[str, List[float]]] = []

            for start_idx in range(0, len(missing_indices), batch_size):
                batch_idxs = missing_indices[start_idx : start_idx + batch_size]
                batch_texts = [texts[idx] for idx in batch_idxs]

                retries = 3
                backoff = 2.0
                while retries > 0:
                    try:
                        response = client.models.embed_content(
                            model=self.model_name,
                            contents=batch_texts,
                            config=types.EmbedContentConfig(
                                task_type="RETRIEVAL_DOCUMENT",
                                output_dimensionality=self.dimension,
                            ),
                        )
                        embeddings = [e.values for e in response.embeddings]
                        for idx, vec in zip(batch_idxs, embeddings):
                            results[idx] = vec
                            to_cache.append((hashes[idx], vec))
                        break
                    except Exception as exc:
                        retries -= 1
                        logger.warning("Gemini batch embedding call failed (%d retries left): %s", retries, exc)
                        if retries == 0:
                            raise LlmProviderException("Failed to embed documents with Gemini API") from exc
                        time.sleep(backoff)
                        backoff *= 2.0

            if to_cache:
                self._save_cached_embeddings(to_cache)

            return [r for r in results if r is not None]
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in Gemini document embedding")
            raise LlmProviderException("Document embedding failed") from exc

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding vector for search query."""
        try:
            if not text:
                return []

            gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not gemini_api_key:
                logger.error("Attempted to embed query without GEMINI_API_KEY or GOOGLE_API_KEY")
                raise ConfigurationException("GEMINI_API_KEY or GOOGLE_API_KEY is not configured")

            client = genai.Client(api_key=gemini_api_key)
            th = hashlib.sha256(text.encode("utf-8")).hexdigest()

            cached = self._get_cached_embedding(th)
            if cached is not None:
                return cached

            retries = 3
            backoff = 1.5
            while retries > 0:
                try:
                    response = client.models.embed_content(
                        model=self.model_name,
                        contents=[text],
                        config=types.EmbedContentConfig(
                            task_type="RETRIEVAL_QUERY",
                            output_dimensionality=self.dimension,
                        ),
                    )
                    vec = response.embeddings[0].values
                    self._save_cached_embeddings([(th, vec)])
                    return vec
                except Exception as exc:
                    retries -= 1
                    logger.warning("Gemini query embedding failed (%d retries left): %s", retries, exc)
                    if retries == 0:
                        raise LlmProviderException("Failed to embed query with Gemini API") from exc
                    time.sleep(backoff)
                    backoff *= 2.0

            raise LlmProviderException("Query embedding failed after retries")
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed embedding search query")
            raise LlmProviderException("Query embedding failed") from exc


# Module-level singleton
_embedding_service: Optional[BaseEmbeddingService] = None


def get_embedding_service() -> BaseEmbeddingService:
    """Return configured embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = GeminiEmbeddingService()
    return _embedding_service


def set_embedding_service(service: Optional[BaseEmbeddingService]) -> None:
    """Explicitly override embedding service instance (for testing/dependency injection)."""
    global _embedding_service
    _embedding_service = service

class FakeEmbeddingService(BaseEmbeddingService):
    """Deterministic fake embedding service for testing."""

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.01 * (i % 50)] * self.dimension for i in range(len(texts))]

    def embed_query(self, text: str) -> list[float]:
        return [0.01] * self.dimension


class EmbeddingService:
    """Service gateway for document and query embeddings, supporting direct classmethod access."""

    @classmethod
    def get_service(cls) -> BaseEmbeddingService:
        return get_embedding_service()

    @classmethod
    def set_service(cls, service: Optional[BaseEmbeddingService]) -> None:
        set_embedding_service(service)

    @classmethod
    def embed_documents(cls, texts: List[str]) -> List[List[float]]:
        return cls.get_service().embed_documents(texts)

    @classmethod
    def embed_query(cls, text: str) -> List[float]:
        return cls.get_service().embed_query(text)


# Aliases for helper usage
EmbeddingHelper = EmbeddingService
get_embedding_helper = get_embedding_service

