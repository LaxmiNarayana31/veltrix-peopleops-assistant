"""Ingestion service managing document parsing, chunking, Qdrant vector indexing, and BM25 search."""

import datetime
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from rank_bm25 import BM25Okapi
from sqlalchemy import delete, select

from app.core.service_state import set_service_ready
from app.dto.document_dto import ChunkDTO, ManifestEntry, ParsedDocument
from app.exceptions.custom_exceptions import AppException, DatabaseException, IngestionException
from app.helper.chunker import StructureAwareChunker
from app.helper.document_parsers import DocumentParser
from app.helper.qdrant.qdrant_manager import QdrantManager
from app.models.holiday_model import HolidayModel
from app.models.ingestion_meta_model import IngestionMetaModel
from app.helper.llm.embedding_helper import EmbeddingService
from app.utils.constants import DEFAULT_CHUNK_SIZE_TOKENS, MONTH_MAP
from config.app_config import CHUNKS_CACHE_PATH, CORPUS_DIR, DB_PATH, MANIFEST_PATH
from config.database import get_db_session

logger = logging.getLogger(__name__)


class IngestionService:
    """Manages document parsing, structure-aware chunking, vector/keyword indexing, and holiday extraction."""

    _all_chunks: List[ChunkDTO] = []
    _chunks_by_id: Dict[str, ChunkDTO] = {}
    _bm25_index: Optional[BM25Okapi] = None
    collection_name: str = "veltrix_corpus"

    @classmethod
    def compute_corpus_fingerprint(cls) -> str:
        """Compute SHA256 fingerprint of manifest and all corpus files for cache invalidation."""
        try:
            hasher = hashlib.sha256()
            manifest_file = Path(MANIFEST_PATH)
            if manifest_file.exists():
                hasher.update(manifest_file.read_bytes())

            corpus_path = Path(CORPUS_DIR)
            if corpus_path.exists():
                for p in sorted(corpus_path.glob("*")):
                    if p.is_file():
                        hasher.update(p.name.encode("utf-8"))
                        hasher.update(str(p.stat().st_size).encode("utf-8"))
                        hasher.update(str(p.stat().st_mtime_ns).encode("utf-8"))

            return hasher.hexdigest()
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed computing corpus fingerprint")
            raise IngestionException("Corpus fingerprint calculation failed") from exc

    @classmethod
    def _get_stored_fingerprint(cls) -> Optional[str]:
        """Fetch stored corpus fingerprint from ingestion_meta table using SQLAlchemy ORM."""
        try:
            with get_db_session() as session:
                stmt = select(IngestionMetaModel.value).where(IngestionMetaModel.key == "corpus_fingerprint")
                return session.scalar(stmt)
        except Exception as exc:
            logger.warning("Could not read stored fingerprint: %s", exc)
            return None

    @classmethod
    def _save_stored_fingerprint(cls, fingerprint: str) -> None:
        """Save new corpus fingerprint and timestamp to ingestion_meta using SQLAlchemy ORM."""
        try:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with get_db_session() as session:
                session.execute(
                    delete(IngestionMetaModel).where(
                        IngestionMetaModel.key.in_(["corpus_fingerprint", "last_ingestion_at"])
                    )
                )
                session.add_all([
                    IngestionMetaModel(key="corpus_fingerprint", value=fingerprint),
                    IngestionMetaModel(key="last_ingestion_at", value=now_iso),
                ])
        except Exception as exc:
            logger.warning("Could not save ingestion fingerprint: %s", exc)

    @classmethod
    def _extract_holidays(cls, doc: ParsedDocument) -> int:
        """Extract holiday rows from calendar document Markdown tables and persist to holidays table."""
        try:
            region = "GLOBAL"
            if doc.metadata and doc.metadata.regions:
                non_global = [r for r in doc.metadata.regions if r != "GLOBAL"]
                if non_global:
                    region = non_global[0]

            effective_date = doc.metadata.effective_date if doc.metadata else "2026-01-01"
            extracted: List[Dict[str, str]] = []

            date_pattern = re.compile(
                r"(?:(\d{1,2})\s*([A-Za-z]+)\s*(\d{4}))|(?:([A-Za-z]+)\s*(\d{1,2}),?\s*(\d{4}))",
                re.IGNORECASE,
            )
            date_words_regex = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{4})\b", re.IGNORECASE)

            for section in doc.sections:
                lines = section.content.splitlines()
                for line in lines:
                    if "|" not in line or "---" in line:
                        continue

                    # Skip document metadata table lines
                    if any(term in line.lower() for term in ("effective date", "document id", "applies to", "classification")):
                        continue

                    match = date_pattern.search(line)
                    if match:
                        groups = match.groups()
                        if groups[0] and groups[1] and groups[2]:
                            day = int(groups[0])
                            month_str = groups[1].lower()[:3]
                            year = int(groups[2])
                        elif groups[3] and groups[4] and groups[5]:
                            month_str = groups[3].lower()[:3]
                            day = int(groups[4])
                            year = int(groups[5])
                        else:
                            continue

                        month = MONTH_MAP.get(month_str)
                        if month:
                            date_str = f"{year:04d}-{month:02d}-{day:02d}"
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            name = "Holiday"
                            weekdays = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
                            for p in parts:
                                if (
                                    p.lower() not in weekdays
                                    and not date_words_regex.search(p)
                                    and len(p) > 2
                                    and not p.replace(" ", "").isdigit()
                                ):
                                    name = p
                                    break
                            extracted.append({"date": date_str, "name": name})

            if not extracted:
                return 0

            with get_db_session() as session:
                session.execute(delete(HolidayModel).where(HolidayModel.source_doc_id == doc.doc_id))
                holiday_models = [
                    HolidayModel(
                        region=region,
                        date=item["date"],
                        name=item["name"],
                        source_doc_id=doc.doc_id,
                        effective_date=effective_date,
                    )
                    for item in extracted
                ]
                session.add_all(holiday_models)

            logger.info("Extracted %d holidays for region %s from %s", len(extracted), region, doc.doc_id)
            return len(extracted)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Error extracting holidays from %s", doc.doc_id)
            raise DatabaseException(f"Failed to store extracted holidays for {doc.doc_id}") from exc

    @classmethod
    def run_ingestion(cls) -> None:
        """Execute full ingestion pipeline: parse documents, chunk, index in Qdrant, build BM25."""
        start_time = time.perf_counter()
        logger.info("Starting corpus ingestion pipeline with Qdrant vector backend")

        try:
            manifest_path = Path(MANIFEST_PATH)
            if not manifest_path.exists():
                logger.error("Manifest file not found at %s", manifest_path)
                raise IngestionException(f"Manifest not found: {manifest_path}")

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            manifest_entries = [ManifestEntry(**item) for item in manifest_data]
            logger.info("Loaded %d document entries from manifest", len(manifest_entries))

            fingerprint = cls.compute_corpus_fingerprint()
            stored_fingerprint = cls._get_stored_fingerprint()
            has_sparse = QdrantManager.has_sparse_vectors(cls.collection_name, "bm25")
            existing_count = QdrantManager.get_collection_point_count(cls.collection_name)
            cache_file = Path(CHUNKS_CACHE_PATH)

            # Fast-path cache hit: if corpus fingerprint matches and Qdrant points + sparse vectors are ready
            if (
                stored_fingerprint == fingerprint
                and has_sparse
                and existing_count > 0
                and cache_file.exists()
            ):
                try:
                    logger.info("Loading corpus chunks from disk cache %s", cache_file)
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_raw = json.load(f)
                    total_chunks = [ChunkDTO(**item) for item in cached_raw]
                    if len(total_chunks) == existing_count:
                        cls._all_chunks = total_chunks
                        cls._chunks_by_id = {c.chunk_id: c for c in total_chunks}
                        corpus_tokens = [cls._tokenize(c.text) for c in total_chunks]
                        cls._bm25_index = BM25Okapi(corpus_tokens)
                        # Ensure calendar holidays are populated even on fast cache restart
                        try:
                            with get_db_session() as session:
                                h_count = len(session.execute(select(HolidayModel)).scalars().all())
                                if h_count < 10:
                                    corpus_dir = Path(CORPUS_DIR)
                                    for entry in manifest_entries:
                                        if entry.doc_type == "calendar":
                                            fpath = corpus_dir / entry.file
                                            if fpath.exists():
                                                cls._extract_holidays(DocumentParser.parse_file(fpath, entry))
                        except Exception as h_err:
                            logger.warning("Could not check/populate holidays during fast start: %s", h_err)

                        elapsed = time.perf_counter() - start_time
                        logger.info("Fast startup: restored %d chunks from cache in %.2fs", len(total_chunks), elapsed)
                        print(f"Documents ingested: {len(manifest_entries)} documents ({len(total_chunks)} chunks)", flush=True)
                        print(f"Documents indexed: {existing_count} chunks in Qdrant", flush=True)
                        set_service_ready(True)
                        return
                except Exception as cache_err:
                    logger.warning("Could not restore chunks from cache (%s), running ingestion", cache_err)

            total_chunks: List[ChunkDTO] = []
            total_holidays = 0
            ocr_pages_count = 0
            failed_docs: List[str] = []

            corpus_dir = Path(CORPUS_DIR)

            for idx, entry in enumerate(manifest_entries, start=1):
                file_path = corpus_dir / entry.file
                if not file_path.exists():
                    logger.warning("Document file %s missing on disk for doc %s", file_path, entry.doc_id)
                    failed_docs.append(entry.doc_id)
                    continue

                try:
                    # Parse full document only when needed for calendar extraction or OCR tracking
                    if entry.doc_type == "calendar" or file_path.name == "memo_hybrid_work_update.pdf":
                        parsed_doc = DocumentParser.parse_file(file_path, entry)
                        if file_path.name == "memo_hybrid_work_update.pdf":
                            ocr_pages_count += len(parsed_doc.sections)
                        if entry.doc_type == "calendar":
                            holidays_count = cls._extract_holidays(parsed_doc)
                            total_holidays += holidays_count

                    doc_chunks = StructureAwareChunker.chunk(file_path, entry)
                    total_chunks.extend(doc_chunks)
                except Exception as doc_exc:
                    logger.warning("Ingestion failed for doc %s (%s): %s", entry.doc_id, entry.file, doc_exc)
                    failed_docs.append(entry.doc_id)

            logger.info("Generated %d chunks from %d successful documents", len(total_chunks), len(manifest_entries) - len(failed_docs))
            print(f"Documents ingested: {len(manifest_entries) - len(failed_docs)} documents ({len(total_chunks)} chunks)", flush=True)

            cls._all_chunks = total_chunks
            cls._chunks_by_id = {c.chunk_id: c for c in total_chunks}

            corpus_tokens = [cls._tokenize(c.text) for c in total_chunks]
            cls._bm25_index = BM25Okapi(corpus_tokens)
            logger.info("BM25 keyword index constructed successfully")

            try:
                cache_file = Path(CHUNKS_CACHE_PATH)
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump([c.model_dump() for c in total_chunks], f)
                logger.info("Saved %d chunks to disk cache %s", len(total_chunks), cache_file)
            except Exception as cache_save_err:
                logger.warning("Could not write chunks cache: %s", cache_save_err)

            fingerprint = cls.compute_corpus_fingerprint()
            stored_fingerprint = cls._get_stored_fingerprint()
            existing_count = QdrantManager.get_collection_point_count(cls.collection_name)
            has_sparse = QdrantManager.has_sparse_vectors(cls.collection_name, "bm25")

            should_rebuild = (
                stored_fingerprint != fingerprint
                or existing_count != len(total_chunks)
                or not has_sparse
            )

            if should_rebuild:
                logger.info(
                    "Rebuilding Qdrant collection (stored_fp=%s current_fp=%s chunks=%d existing=%d)",
                    stored_fingerprint,
                    fingerprint,
                    len(total_chunks),
                    existing_count,
                )
                QdrantManager.get_or_create_collection(
                    cls.collection_name, dense_dimension=768, force_recreate=True
                )

                batch_size = 100
                total_batches = (len(total_chunks) + batch_size - 1) // batch_size
                for i in range(0, len(total_chunks), batch_size):
                    batch_num = (i // batch_size) + 1
                    batch = total_chunks[i : i + batch_size]
                    batch_texts = [c.embedded_text for c in batch]
                    logger.info(
                        "Generating embeddings for batch %d/%d (chunks %d to %d)...",
                        batch_num,
                        total_batches,
                        i + 1,
                        i + len(batch),
                    )
                    batch_embeddings = EmbeddingService.embed_documents(batch_texts)

                    QdrantManager.upsert_chunks(
                        collection_name=cls.collection_name,
                        chunks=batch,
                        dense_vectors=batch_embeddings,
                    )

                cls._save_stored_fingerprint(fingerprint)
                logger.info("Indexed %d chunks into Qdrant vector store with fingerprint %s", len(total_chunks), fingerprint[:8])
                print(f"Documents indexed: {len(total_chunks)} chunks in Qdrant", flush=True)
            else:
                logger.info("Qdrant collection fingerprint matched (%s); skipping re-indexing", fingerprint[:8])
                print(f"Documents indexed: {existing_count} chunks in Qdrant", flush=True)

            elapsed = time.perf_counter() - start_time
            logger.info(
                "Ingestion summary: docs=%d chunks=%d ocr_pages=%d holidays=%d failed_docs=%d duration=%.2fs",
                len(manifest_entries),
                len(total_chunks),
                ocr_pages_count,
                total_holidays,
                len(failed_docs),
                elapsed,
            )

            set_service_ready(True)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Corpus ingestion pipeline failed")
            raise IngestionException("Corpus ingestion failed") from exc

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """Simple alphanumeric tokenizer for BM25 indexing."""
        return re.findall(r"\w+", text.lower())

    @classmethod
    def _ensure_chunks_loaded(cls) -> None:
        """Ensure chunks and BM25 are restored from disk cache if not yet loaded in this process."""
        if not cls._all_chunks or not cls._chunks_by_id:
            cache_file = Path(CHUNKS_CACHE_PATH)
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_raw = json.load(f)
                    total_chunks = [ChunkDTO(**item) for item in cached_raw]
                    cls._all_chunks = total_chunks
                    cls._chunks_by_id = {c.chunk_id: c for c in total_chunks}
                    corpus_tokens = [cls._tokenize(c.text) for c in total_chunks]
                    cls._bm25_index = BM25Okapi(corpus_tokens)
                except Exception as e:
                    logger.warning("Could not auto-load chunks cache: %s", e)

    @classmethod
    def get_all_chunks(cls) -> List[ChunkDTO]:
        """Return all in-memory chunks."""
        cls._ensure_chunks_loaded()
        return cls._all_chunks

    @classmethod
    def get_chunk_by_id(cls, chunk_id: str) -> Optional[ChunkDTO]:
        """Retrieve chunk by its unique chunk ID."""
        cls._ensure_chunks_loaded()
        return cls._chunks_by_id.get(chunk_id)

    @classmethod
    def get_bm25_index(cls) -> Optional[BM25Okapi]:
        """Return initialized BM25 index instance."""
        cls._ensure_chunks_loaded()
        return cls._bm25_index

    @classmethod
    def get_collection_count(cls) -> int:
        """Return point count in Qdrant collection."""
        return QdrantManager.get_collection_point_count(cls.collection_name)

    @classmethod
    def run(cls) -> None:
        """Execute corpus ingestion via classmethod."""
        cls.run_ingestion()


# Module-level singleton
_ingestion_service: Optional[IngestionService] = None


def get_ingestion_service() -> IngestionService:
    """Return singleton IngestionService instance."""
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service

# Aliases for helper usage
IngestionHelper = IngestionService
get_ingestion_helper = get_ingestion_service
