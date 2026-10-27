"""Structure-aware document chunking using section hierarchy with per-file disk caching."""

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import List

from app.dto.document_dto import ChunkDTO, DocumentSection, ManifestEntry
from app.exceptions.custom_exceptions import AppException, IngestionException
from app.helper.document_parsers import DocumentParser
from app.utils.constants import DEFAULT_CHUNK_SIZE_TOKENS
from app.utils.token_counter import TokenCounter

logger = logging.getLogger(__name__)

CACHE_DIR = Path("./data/chunks_cache")


class StructureAwareChunker:
    """Structure-aware chunker utilizing document section hierarchy with per-document disk caching."""

    @classmethod
    def _get_cache_path(cls, file_path: Path, manifest: ManifestEntry, target_tokens: int) -> Path:
        """Derive deterministic cache path for a document based on file stat and manifest metadata."""
        try:
            stat = file_path.stat()
            sig = f"{manifest.doc_id}_{manifest.effective_date}_{stat.st_size}_{stat.st_mtime_ns}_{target_tokens}"
            h = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            return CACHE_DIR / f"{manifest.doc_id}_{h}.json"
        except Exception:
            return CACHE_DIR / f"{manifest.doc_id}_default.json"

    @classmethod
    def chunk(
        cls,
        file_path: Path,
        manifest: ManifestEntry,
        target_tokens: int = DEFAULT_CHUNK_SIZE_TOKENS,
    ) -> List[ChunkDTO]:
        """Chunk a document file, reusing cached chunks if the file was already parsed."""
        cache_file = cls._get_cache_path(file_path, manifest, target_tokens)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                chunks = [ChunkDTO(**item) for item in raw_list]
                if chunks:
                    logger.debug("Reusing cached chunks for %s from %s", manifest.doc_id, cache_file.name)
                    return chunks
            except Exception as read_err:
                logger.warning("Could not read chunk cache %s: %s", cache_file, read_err)

        try:
            parsed_doc = DocumentParser.parse_file(file_path, manifest)
            chunks: List[ChunkDTO] = []
            chunk_idx = 0

            for section in parsed_doc.sections:
                section_text = section.content.strip()
                if not section_text:
                    continue

                locator = section.locator or manifest.title
                sec_tokens = TokenCounter.count_tokens(section_text)

                if sec_tokens <= target_tokens:
                    embedded_text = f"[{manifest.title} - {locator}]\n{section_text}"
                    chunk_dto = ChunkDTO(
                        chunk_id=f"{manifest.doc_id}_{chunk_idx:03d}",
                        doc_id=manifest.doc_id,
                        title=manifest.title,
                        locator=locator,
                        text=section_text,
                        embedded_text=embedded_text,
                        token_count=sec_tokens,
                        doc_type=manifest.doc_type,
                        regions=manifest.regions,
                        effective_date=manifest.effective_date,
                        access_level=manifest.access_level,
                    )
                    chunks.append(chunk_dto)
                    chunk_idx += 1
                else:
                    # Split oversized section by paragraphs or sentences
                    sub_chunks = cls._split_oversized_section(section_text, target_tokens)
                    for sub in sub_chunks:
                        if not sub.strip():
                            continue
                        sub_token_len = TokenCounter.count_tokens(sub)
                        embedded_text = f"[{manifest.title} - {locator}]\n{sub}"
                        chunk_dto = ChunkDTO(
                            chunk_id=f"{manifest.doc_id}_{chunk_idx:03d}",
                            doc_id=manifest.doc_id,
                            title=manifest.title,
                            locator=locator,
                            text=sub,
                            embedded_text=embedded_text,
                            token_count=sub_token_len,
                            doc_type=manifest.doc_type,
                            regions=manifest.regions,
                            effective_date=manifest.effective_date,
                            access_level=manifest.access_level,
                        )
                        chunks.append(chunk_dto)
                        chunk_idx += 1

            if not chunks:
                # Fallback single chunk
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")[:1000]
                chunks.append(
                    ChunkDTO(
                        chunk_id=f"{manifest.doc_id}_000",
                        doc_id=manifest.doc_id,
                        title=manifest.title,
                        locator=manifest.title,
                        text=raw_text,
                        embedded_text=f"[{manifest.title}]\n{raw_text}",
                        token_count=TokenCounter.count_tokens(raw_text),
                        doc_type=manifest.doc_type,
                        regions=manifest.regions,
                        effective_date=manifest.effective_date,
                        access_level=manifest.access_level,
                    )
                )

            # Persist chunks to per-document disk cache
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump([c.model_dump() for c in chunks], f)
                logger.debug("Cached %d chunks for %s to %s", len(chunks), manifest.doc_id, cache_file.name)
            except Exception as write_err:
                logger.warning("Could not persist chunk cache %s: %s", cache_file, write_err)

            return chunks
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed chunking document %s", file_path.name)
            raise IngestionException(f"Error chunking document {manifest.doc_id}: {exc}") from exc

    @classmethod
    def _split_oversized_section(cls, text: str, max_tokens: int) -> List[str]:
        """Split text exceeding token target into smaller coherent units."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        result: List[str] = []
        current_block: List[str] = []
        current_tokens = 0

        for p in paragraphs:
            p_tokens = TokenCounter.count_tokens(p)
            if current_tokens + p_tokens <= max_tokens:
                current_block.append(p)
                current_tokens += p_tokens
            else:
                if current_block:
                    result.append("\n\n".join(current_block))
                    current_block = []
                    current_tokens = 0

                if p_tokens <= max_tokens:
                    current_block.append(p)
                    current_tokens = p_tokens
                else:
                    # Paragraph itself exceeds max_tokens; split by sentences
                    sentences = re.split(r"(?<=[.!?])\s+", p)
                    sent_block: List[str] = []
                    sent_tokens = 0
                    for s in sentences:
                        s_tok = TokenCounter.count_tokens(s)
                        if sent_tokens + s_tok <= max_tokens:
                            sent_block.append(s)
                            sent_tokens += s_tok
                        else:
                            if sent_block:
                                result.append(" ".join(sent_block))
                            sent_block = [s]
                            sent_tokens = s_tok
                    if sent_block:
                        result.append(" ".join(sent_block))

        if current_block:
            result.append("\n\n".join(current_block))

        return result
