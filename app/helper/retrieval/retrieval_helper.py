"""Retrieval service providing role-filtered hybrid vector and keyword retrieval with strict token budget packing."""

import logging
import re
from datetime import date
from typing import Dict, List, Optional, Set

from app.dto.chat_dto import RequestContext
from app.dto.document_dto import ChunkDTO
from app.dto.retrieval_dto import RetrievalResult
from app.exceptions.custom_exceptions import AppException, RetrievalException, TokenBudgetExceededException
from app.helper.qdrant.qdrant_manager import QdrantManager
from app.helper.access.access_helper import AccessService
from app.helper.ingestion.ingestion_helper import IngestionService
from app.helper.llm.embedding_helper import EmbeddingService
from app.utils.constants import MAX_CORPUS_TOKENS_BUDGET, TARGET_CORPUS_PACKING_BUDGET
from config.app_config import REFERENCE_DATE

logger = logging.getLogger(__name__)


class RetrievalService:
    """Provides role-filtered hybrid vector and keyword retrieval with strict token budget packing."""

    @classmethod
    def retrieve(
        cls,
        ctx: RequestContext,
        query: str,
        reference_date: Optional[date] = None,
        max_budget: int = TARGET_CORPUS_PACKING_BUDGET,
    ) -> RetrievalResult:
        """Perform pre-filtered hybrid search constrained by role, region, date, and token budget."""
        try:
            ref_date = reference_date or REFERENCE_DATE
            eligible_set, upcoming_set = AccessService.eligible_doc_ids(ctx, ref_date)
            allowed_set = eligible_set | upcoming_set

            if not allowed_set:
                logger.info("No documents eligible for emp=%s with role=%s region=%s", ctx.employee_id, ctx.role, ctx.region)
                return RetrievalResult(
                    eligible_doc_ids=sorted(eligible_set),
                    upcoming_doc_ids=sorted(upcoming_set),
                )

            vector_ranks: Dict[str, int] = {}
            try:
                col_name = "veltrix_corpus"
                if QdrantManager.collection_exists(col_name) and QdrantManager.get_collection_point_count(col_name) > 0:
                    query_embedding = EmbeddingService.embed_query(query)
                    search_results = QdrantManager.search_dense(
                        collection_name=col_name,
                        query_vector=query_embedding,
                        allowed_doc_ids=sorted(list(allowed_set)),
                        role=ctx.role,
                        region=ctx.region,
                        limit=40,
                    )
                    for rank, res in enumerate(search_results):
                        cid = res["payload"].get("chunk_id")
                        if cid:
                            vector_ranks[cid] = rank
            except Exception as v_exc:
                logger.warning("Vector retrieval encountered an error: %s", v_exc)

            bm25_ranks: Dict[str, int] = {}
            try:
                col_name = "veltrix_corpus"
                if QdrantManager.has_sparse_vectors(col_name, "bm25"):
                    sparse_results = QdrantManager.search_sparse(
                        collection_name=col_name,
                        query_text=query,
                        allowed_doc_ids=sorted(list(allowed_set)),
                        role=ctx.role,
                        region=ctx.region,
                        limit=40,
                    )
                    for rank, res in enumerate(sparse_results):
                        cid = res["payload"].get("chunk_id")
                        if cid:
                            bm25_ranks[cid] = rank
            except Exception as s_exc:
                logger.debug("Qdrant sparse search fallback to in-memory BM25: %s", s_exc)

            if not bm25_ranks:
                bm25_index = IngestionService.get_bm25_index()
                all_chunks = IngestionService.get_all_chunks()

                if bm25_index and all_chunks:
                    query_tokens = re.findall(r"\w+", query.lower())
                    if query_tokens:
                        bm25_scores = bm25_index.get_scores(query_tokens)
                        scored_allowed = [
                            (chunk.chunk_id, bm25_scores[idx])
                            for idx, chunk in enumerate(all_chunks)
                            if chunk.doc_id in allowed_set and bm25_scores[idx] > 0
                        ]
                        scored_allowed.sort(key=lambda x: x[1], reverse=True)
                        for rank, (chunk_id, _) in enumerate(scored_allowed[:40]):
                            bm25_ranks[chunk_id] = rank

            fused_scores = QdrantManager.reciprocal_rank_fusion(vector_ranks, bm25_ranks, k=60)
            if not fused_scores:
                for c in all_chunks:
                    if c.doc_id in allowed_set:
                        fused_scores[c.chunk_id] = 0.01
                        if len(fused_scores) >= 15:
                            break

            sorted_chunk_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

            doc_to_chunks: Dict[str, List[ChunkDTO]] = {}
            for cid in sorted_chunk_ids:
                chunk = IngestionService.get_chunk_by_id(cid)
                if chunk:
                    doc_to_chunks.setdefault(chunk.doc_id, []).append(chunk)

            diverse_chunks: List[ChunkDTO] = []
            max_depth = max((len(clist) for clist in doc_to_chunks.values()), default=0)
            for depth in range(max_depth):
                for doc_id, clist in doc_to_chunks.items():
                    if depth < len(clist):
                        diverse_chunks.append(clist[depth])

            packed_eligible: List[ChunkDTO] = []
            packed_upcoming: List[ChunkDTO] = []
            total_tokens = 0
            seen_chunk_ids: Set[str] = set()

            for chunk in diverse_chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue

                chunk_tokens = chunk.token_count + 30
                if total_tokens + chunk_tokens > max_budget:
                    continue

                seen_chunk_ids.add(chunk.chunk_id)
                total_tokens += chunk_tokens

                if chunk.doc_id in eligible_set:
                    packed_eligible.append(chunk)
                else:
                    packed_upcoming.append(chunk)

            if total_tokens > MAX_CORPUS_TOKENS_BUDGET:
                logger.error("Token budget exceeded limit: %d > %d", total_tokens, MAX_CORPUS_TOKENS_BUDGET)
                raise TokenBudgetExceededException("Corpus text packing exceeded 3,000 token limit")

            all_packed = packed_eligible + packed_upcoming
            logger.info(
                "Retrieval completed: eligible=%d upcoming=%d total_tokens=%d for emp=%s",
                len(packed_eligible),
                len(packed_upcoming),
                total_tokens,
                ctx.employee_id,
            )

            return RetrievalResult(
                eligible_chunks=packed_eligible,
                upcoming_chunks=packed_upcoming,
                all_chunks=all_packed,
                total_tokens=total_tokens,
                eligible_doc_ids=sorted(list(eligible_set)),
                upcoming_doc_ids=sorted(list(upcoming_set)),
            )
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Retrieval failed for emp=%s", ctx.employee_id)
            raise RetrievalException("Retrieval operation failed") from exc


# Module-level singleton
_retrieval_service: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    """Return singleton RetrievalService instance."""
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service

# Aliases for helper usage
RetrievalHelper = RetrievalService
get_retrieval_helper = get_retrieval_service
