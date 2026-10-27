from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ManifestEntry(BaseModel):
    """Manifest entry describing a document's metadata and access parameters."""
    model_config = ConfigDict(extra="ignore")
    doc_id: str
    file: str
    title: str
    doc_type: str 
    regions: List[str]
    effective_date: str  # YYYY-MM-DD
    access_level: str  # all | managers | hr


class DocumentSection(BaseModel):
    """Section or page extracted from a parsed document."""
    locator: str  # heading or "p. N"
    content: str
    page_number: Optional[int] = None

    @property
    def text(self) -> str:
        """Alias for content attribute."""
        return self.content


class ParsedDocument(BaseModel):
    """Normalized document representation before chunking."""
    doc_id: str
    title: str
    sections: List[DocumentSection]
    metadata: ManifestEntry

    @property
    def manifest(self) -> ManifestEntry:
        """Alias for metadata attribute."""
        return self.metadata


class ChunkDTO(BaseModel):
    """Structure-aware chunk ready for indexing and retrieval."""
    chunk_id: str
    doc_id: str
    title: str
    locator: str
    text: str
    embedded_text: str
    token_count: int
    doc_type: str
    regions: List[str]
    effective_date: str
    access_level: str
