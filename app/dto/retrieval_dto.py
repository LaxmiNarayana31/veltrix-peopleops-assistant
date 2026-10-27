"""DTO models for retrieval, search results, and precedence resolution."""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.dto.chat_dto import CitationDTO
from app.dto.document_dto import ChunkDTO


class PrecedenceCandidate(BaseModel):
    """Document candidate holding an extracted rule value and metadata."""

    doc_id: str
    locator: str
    doc_type: str
    regions: List[str]
    effective_date: str
    value: str
    normalized_value: Optional[str] = None


class PrecedenceResolutionResult(BaseModel):
    """Output of deterministic Section 5 precedence evaluation."""

    winners: List[PrecedenceCandidate] = Field(default_factory=list)
    conflict: bool = False
    upcoming_change: Optional[PrecedenceCandidate] = None
    citations: List[CitationDTO] = Field(default_factory=list)
    resolution_notes: str = ""


class RetrievalResult(BaseModel):
    """Result of pre-filtered hybrid retrieval with token budget allocation."""

    eligible_chunks: List[ChunkDTO] = Field(default_factory=list)
    upcoming_chunks: List[ChunkDTO] = Field(default_factory=list)
    all_chunks: List[ChunkDTO] = Field(default_factory=list)
    total_tokens: int = 0
    eligible_doc_ids: List[str] = Field(default_factory=list)
    upcoming_doc_ids: List[str] = Field(default_factory=list)
