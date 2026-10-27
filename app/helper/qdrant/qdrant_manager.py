"""Qdrant Vector Database integration and collection manager."""

import atexit
import collections
import hashlib
import logging
import math
import os
import re
import time
from typing import Any, Dict, List, Optional
import uuid

from qdrant_client import QdrantClient, models
from qdrant_client.models import PointStruct

from app.dto.document_dto import ChunkDTO
from config.app_config import QDRANT_API_KEY, QDRANT_URL

logger = logging.getLogger(__name__)

DEFAULT_DOCKER_QDRANT_URL = "http://localhost:6333"


def sanitize_collection_name(name: str) -> str:
    """Sanitize collection name to meet Qdrant standards."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name or "")).strip("_").lower()
    return clean[:64] or "veltrix_corpus"


class QdrantManager:
    """Manages Qdrant vector database operations, hybrid collections, and quantized search."""

    _client: Optional[QdrantClient] = None

    @classmethod
    def get_client(cls, url: Optional[str] = None, api_key: Optional[str] = None) -> QdrantClient:
        """Initialize or return singleton QdrantClient connection.

        If QDRANT_URL is set (and optional QDRANT_API_KEY), connects to that instance.
        If empty, connects to the local Docker Compose service at http://localhost:6333.
        Does not fall back to local machine disk storage.
        """
        if cls._client is None:
            raw_url = str(url or QDRANT_URL or "").strip()
            raw_api_key = str(api_key or QDRANT_API_KEY or "").strip() or None
            target_url = raw_url if raw_url else DEFAULT_DOCKER_QDRANT_URL

            max_retries = 5
            connected = False
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info("Initializing Qdrant client connecting to service URL: %s (attempt %d/%d)", target_url, attempt, max_retries)
                    client = QdrantClient(
                        url=target_url,
                        api_key=raw_api_key,
                        timeout=5,
                        check_compatibility=False,
                    )
                    client.get_collections()
                    cls._client = client
                    atexit.register(cls.close)
                    connected = True
                    break
                except Exception as exc:
                    last_err = exc
                    if attempt < max_retries:
                        time.sleep(2)

            if not connected:
                logger.warning(
                    "Could not connect to Qdrant service at %s after %d attempts: %s. Using in-memory client for testing/offline mode.",
                    target_url,
                    max_retries,
                    last_err,
                )
                cls._client = QdrantClient(location=":memory:")
                atexit.register(cls.close)

        return cls._client

    @classmethod
    def close(cls) -> None:
        """Cleanly close Qdrant client connection."""
        try:
            if cls._client is not None:
                cls._client.close()
                cls._client = None
        except Exception as exc:
            logger.warning("Error closing Qdrant client: %s", exc)

    @classmethod
    def collection_exists(cls, collection_name: str) -> bool:
        """Check whether a collection exists in Qdrant."""
        try:
            clean_name = sanitize_collection_name(collection_name)
            return cls.get_client().collection_exists(clean_name)
        except Exception as exc:
            logger.warning("Error checking collection existence for %s: %s", collection_name, exc)
            return False

    @classmethod
    def get_collection_point_count(cls, collection_name: str) -> int:
        """Retrieve total point count within collection."""
        try:
            clean_name = sanitize_collection_name(collection_name)
            if not cls.collection_exists(clean_name):
                return 0
            info = cls.get_client().get_collection(clean_name)
            return info.points_count or 0
        except Exception as exc:
            logger.warning("Error getting point count for %s: %s", collection_name, exc)
            return 0

    @classmethod
    def has_sparse_vectors(cls, collection_name: str, vector_name: str = "bm25") -> bool:
        """Check whether the collection has sparse vector support enabled."""
        try:
            clean_name = sanitize_collection_name(collection_name)
            if not cls.collection_exists(clean_name):
                return False
            info = cls.get_client().get_collection(clean_name)
            sparse_map = getattr(info.config.params, "sparse_vectors", None)
            return bool(sparse_map and vector_name in sparse_map)
        except Exception as exc:
            logger.debug("Error checking sparse vector config for %s: %s", collection_name, exc)
            return False

    @staticmethod
    def compute_sparse_vector(text: str) -> models.SparseVector:
        """Compute a deterministic BM25 / token-frequency sparse vector for Qdrant indexing."""
        words = re.findall(r"\w+", str(text or "").lower())
        if not words:
            return models.SparseVector(indices=[], values=[])

        counts = collections.Counter(words)
        pairs: List[tuple[int, float]] = []
        for word, count in counts.items():
            # Generate deterministic 31-bit positive integer index for each token
            token_hash = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16) % 2147483647
            # Sub-linear term frequency weight: 1.0 + ln(count)
            weight = float(round(1.0 + math.log(count), 4))
            pairs.append((token_hash, weight))

        # Qdrant requires sparse vector indices to be sorted
        pairs.sort(key=lambda x: x[0])
        indices = [p[0] for p in pairs]
        values = [p[1] for p in pairs]
        return models.SparseVector(indices=indices, values=values)

    @classmethod
    def delete_collection(cls, collection_name: str) -> None:
        """Delete collection if it exists."""
        try:
            clean_name = sanitize_collection_name(collection_name)
            if cls.collection_exists(clean_name):
                cls.get_client().delete_collection(clean_name)
                logger.info("Deleted Qdrant collection: %s", clean_name)
        except Exception as exc:
            logger.warning("Error deleting collection %s: %s", collection_name, exc)

    @classmethod
    def get_or_create_collection(
        cls,
        collection_name: str,
        dense_dimension: int = 768,
        quantization_type: str = "binary",
        force_recreate: bool = False,
    ) -> str:
        """Ensure collection exists with vector quantization, HNSW tuning, and payload indexing."""
        clean_name = sanitize_collection_name(collection_name)
        exists = cls.collection_exists(clean_name)
        client = cls.get_client()

        if exists and force_recreate:
            client.delete_collection(clean_name)
            exists = False

        if not exists:
            quantization_config: Optional[models.QuantizationConfig] = None
            if quantization_type.lower() == "binary":
                quantization_config = models.BinaryQuantization(
                    binary=models.BinaryQuantizationConfig(always_ram=True)
                )
            elif quantization_type.lower() == "scalar":
                quantization_config = models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    )
                )

            hnsw_config = models.HnswConfigDiff(
                m=16,
                ef_construct=100,
                on_disk=False,
            )

            optimizers_config = models.OptimizersConfigDiff(
                default_segment_number=2,
            )

            sparse_config = {
                "bm25": models.SparseVectorParams()
            }

            try:
                client.create_collection(
                    collection_name=clean_name,
                    vectors_config=models.VectorParams(
                        size=dense_dimension,
                        distance=models.Distance.COSINE,
                        on_disk=True,
                    ),
                    sparse_vectors_config=sparse_config,
                    hnsw_config=hnsw_config,
                    quantization_config=quantization_config,
                    optimizers_config=optimizers_config,
                    on_disk_payload=True,
                )
            except Exception as err:
                logger.debug("Creating collection with fallback parameters: %s", err)
                client.create_collection(
                    collection_name=clean_name,
                    vectors_config=models.VectorParams(
                        size=dense_dimension,
                        distance=models.Distance.COSINE,
                    ),
                    sparse_vectors_config=sparse_config,
                    quantization_config=quantization_config,
                )

            for field in ["doc_id", "access_level", "region"]:
                try:
                    client.create_payload_index(
                        collection_name=clean_name,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass

            logger.info(
                "Created Qdrant collection %s with quantization=%s, on_disk=True, and payload indices",
                clean_name,
                quantization_type,
            )

        return clean_name

    @classmethod
    def upsert_chunks(
        cls,
        collection_name: str,
        chunks: List[ChunkDTO],
        dense_vectors: List[List[float]],
    ) -> int:
        """Batch upsert document chunks into collection with dense + BM25 sparse vectors and metadata payloads."""
        clean_name = sanitize_collection_name(collection_name)
        points: List[PointStruct] = []

        for chunk, emb in zip(chunks, dense_vectors):
            unique_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
            payload = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "locator": chunk.locator,
                "doc_type": chunk.doc_type,
                "region": chunk.regions[0] if chunk.regions else "GLOBAL",
                "effective_date": chunk.effective_date,
                "access_level": chunk.access_level,
                "token_count": chunk.token_count,
            }
            sparse_vec = cls.compute_sparse_vector(chunk.text)
            points.append(
                PointStruct(
                    id=unique_id,
                    vector={
                        "": emb,
                        "bm25": sparse_vec,
                    },
                    payload=payload,
                )
            )

        if points:
            cls.get_client().upsert(collection_name=clean_name, points=points)
            logger.info("Upserted %d points into Qdrant collection %s", len(points), clean_name)

        return len(points)

    @classmethod
    def build_filter(
        cls,
        allowed_doc_ids: Optional[List[str]] = None,
        role: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[models.Filter]:
        """Construct role-based, region-based, and/or document ID Qdrant pre-filter per TASK.pdf Section 5 & 7."""
        must_conditions: List[models.Condition] = []

        # 1. Role-based access level filtering
        if role:
            role_val = role.value if hasattr(role, "value") else str(role)
            role_str = str(role_val).lower()
            if role_str == "hr":
                allowed_levels = ["all", "managers", "hr"]
            elif role_str == "manager":
                allowed_levels = ["all", "managers"]
            else:
                allowed_levels = ["all"]
            must_conditions.append(
                models.FieldCondition(
                    key="access_level",
                    match=models.MatchAny(any=allowed_levels),
                )
            )

        # 2. Region-based filtering (matches employee's region or GLOBAL)
        if region:
            region_val = region.value if hasattr(region, "value") else str(region)
            reg_str = str(region_val).upper()
            must_conditions.append(
                models.FieldCondition(
                    key="region",
                    match=models.MatchAny(any=[reg_str, "GLOBAL"]),
                )
            )

        # 3. Document ID filtering (from Precedence & Eligibility engine)
        if allowed_doc_ids is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=allowed_doc_ids),
                )
            )

        if not must_conditions:
            return None
        return models.Filter(must=must_conditions)

    @classmethod
    def search_sparse(
        cls,
        collection_name: str,
        query_text: str,
        allowed_doc_ids: Optional[List[str]] = None,
        role: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 40,
    ) -> List[Dict[str, Any]]:
        """Search sparse vector index (BM25) in Qdrant with role-based and document pre-filtering."""
        clean_name = sanitize_collection_name(collection_name)
        if not cls.collection_exists(clean_name):
            return []

        sparse_vector = cls.compute_sparse_vector(query_text)
        if not sparse_vector.indices:
            return []

        query_filter = cls.build_filter(
            allowed_doc_ids=allowed_doc_ids,
            role=role,
            region=region,
        )

        try:
            results = cls.get_client().query_points(
                collection_name=clean_name,
                query=sparse_vector,
                using="bm25",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            matched_points = results.points or []
            return [
                {
                    "point_id": p.id,
                    "score": getattr(p, "score", 0.0),
                    "payload": p.payload or {},
                }
                for p in matched_points
            ]
        except Exception as exc:
            logger.warning("Qdrant sparse search error in %s: %s", clean_name, exc)
            return []

    @classmethod
    def search_dense(
        cls,
        collection_name: str,
        query_vector: List[float],
        allowed_doc_ids: Optional[List[str]] = None,
        role: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 40,
        hnsw_ef: int = 128,
        oversampling: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """Search dense vectors with quantization rescoring, HNSW ef tuning, and role-based pre-filtering."""
        clean_name = sanitize_collection_name(collection_name)
        if not cls.collection_exists(clean_name):
            return []

        search_params = models.SearchParams(
            hnsw_ef=hnsw_ef,
            quantization=models.QuantizationSearchParams(
                ignore=False,
                rescore=True,
                oversampling=oversampling,
            ),
        )

        query_filter = cls.build_filter(
            allowed_doc_ids=allowed_doc_ids,
            role=role,
            region=region,
        )

        try:
            results = cls.get_client().query_points(
                collection_name=clean_name,
                query=query_vector,
                query_filter=query_filter,
                search_params=search_params,
                limit=limit,
                with_payload=True,
            )
            matched_points = results.points or []
            return [
                {
                    "point_id": p.id,
                    "score": getattr(p, "score", 0.0),
                    "payload": p.payload or {},
                }
                for p in matched_points
            ]
        except Exception as exc:
            logger.warning("Qdrant search error in %s: %s", clean_name, exc)
            return []

    @staticmethod
    def reciprocal_rank_fusion(
        dense_ranks: Dict[str, int],
        sparse_ranks: Dict[str, int],
        k: int = 60,
    ) -> Dict[str, float]:
        """Combine dense and sparse search rankings using Reciprocal Rank Fusion (RRF).

        Formula: RRF_score(d) = sum(1 / (k + rank_i(d)))
        Reference: https://qdrant.tech/articles/hybrid-search/
        """
        all_candidate_ids = set(dense_ranks.keys()) | set(sparse_ranks.keys())
        fused_scores: Dict[str, float] = {}
        for cid in all_candidate_ids:
            v_rank = dense_ranks.get(cid, 100)
            s_rank = sparse_ranks.get(cid, 100)
            score = (1.0 / (k + v_rank)) + (1.0 / (k + s_rank))
            fused_scores[cid] = score
        return fused_scores

    @classmethod
    def get_instance(cls) -> "QdrantManager":
        """Return QdrantManager class for backward compatibility."""
        return cls


def get_qdrant_manager() -> type[QdrantManager]:
    """Return QdrantManager class for backward compatibility."""
    return QdrantManager
