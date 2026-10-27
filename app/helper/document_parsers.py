"""Document parsing using PyMuPDF, python-docx, and BeautifulSoup with disk caching."""

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import List, Optional

import bs4
import docx
import pymupdf

from app.dto.document_dto import DocumentSection, ManifestEntry, ParsedDocument
from app.exceptions.custom_exceptions import AppException, FileFormatException, IngestionException
from config.app_config import OCR_CACHE_DIR

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md"}
PARSED_CACHE_DIR = Path("./data/parsed_docs_cache")


class DocumentParser:
    """Parses documents (PDF, DOCX, HTML, Markdown) into structured Markdown sections without heavy DL dependencies."""

    @classmethod
    def _get_cache_path(cls, file_path: Path, manifest: ManifestEntry) -> Path:
        """Derive deterministic cache path for a parsed document."""
        try:
            stat = file_path.stat()
            sig = f"{manifest.doc_id}_{manifest.effective_date}_{stat.st_size}_{stat.st_mtime_ns}"
            h = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
            PARSED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            return PARSED_CACHE_DIR / f"{manifest.doc_id}_{h}.json"
        except Exception:
            return PARSED_CACHE_DIR / f"{manifest.doc_id}_default.json"

    @classmethod
    def parse_file(cls, file_path: Path, manifest: ManifestEntry) -> ParsedDocument:
        """Parse document into structured sections using lightweight native parsers with disk caching."""
        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise FileFormatException(f"Unsupported file format '{suffix}' for {file_path.name}")

        cache_file = cls._get_cache_path(file_path, manifest)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ParsedDocument(**data)
            except Exception as read_err:
                logger.warning("Could not read parsed doc cache %s: %s", cache_file, read_err)

        try:
            if suffix == ".pdf":
                markdown_text = cls._parse_pdf(file_path, manifest)
            elif suffix == ".docx":
                markdown_text = cls._parse_docx(file_path, manifest)
            elif suffix in (".html", ".htm"):
                markdown_text = cls._parse_html(file_path, manifest)
            else:  # .md
                markdown_text = file_path.read_text(encoding="utf-8", errors="replace")

            if not markdown_text or not markdown_text.strip():
                raise IngestionException(f"Empty extraction for {file_path.name}")

            sections = cls._markdown_to_sections(markdown_text, manifest)

            parsed = ParsedDocument(
                doc_id=manifest.doc_id,
                title=manifest.title,
                sections=sections,
                metadata=manifest,
            )

            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(parsed.model_dump(), f)
            except Exception as write_err:
                logger.warning("Could not persist parsed doc cache %s: %s", cache_file, write_err)

            return parsed
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed parsing document %s", file_path.name)
            raise IngestionException(f"Error parsing document {manifest.doc_id}: {exc}") from exc

    @classmethod
    def _parse_pdf(cls, file_path: Path, manifest: ManifestEntry) -> str:
        """Extract text and tables from PDF using PyMuPDF, with OCR cache support for scanned pages."""
        doc = pymupdf.open(file_path)
        page_texts: List[str] = []

        for page_idx, page in enumerate(doc):
            text = page.get_text("text").strip()

            # Check for scanned page without text layer
            if len(text) < 20:
                cached_ocr = cls._get_cached_ocr(file_path, page_idx)
                if cached_ocr:
                    text = cached_ocr
                else:
                    text = cls._ocr_page_fallback(page, file_path, page_idx)

            # Extract tables if present and format as Markdown tables
            tables = page.find_tables()
            table_markdowns: List[str] = []
            if tables:
                for tab in tables:
                    extracted = tab.extract()
                    if extracted and len(extracted) > 1:
                        md_tab = cls._matrix_to_markdown_table(extracted)
                        if md_tab:
                            table_markdowns.append(md_tab)

            page_content = text
            if table_markdowns:
                # Append extracted structured tables
                page_content = f"{page_content}\n\n" + "\n\n".join(table_markdowns)

            if page_content.strip():
                page_texts.append(page_content.strip())

        return "\n\n".join(page_texts)

    @classmethod
    def _matrix_to_markdown_table(cls, rows: List[List[Optional[str]]]) -> str:
        """Convert a 2D matrix of cells into a GitHub Flavored Markdown table."""
        if not rows or not rows[0]:
            return ""

        cleaned_rows: List[List[str]] = []
        for row in rows:
            clean_cells = []
            for cell in row:
                c = str(cell or "").replace("\n", " ").strip()
                # Insert spaces between numbers and adjacent words, and between merged words
                c = re.sub(r"(\d+)([A-Za-z]+)", r"\1 \2", c)
                c = re.sub(r"([A-Za-z]+)(\d+)", r"\1 \2", c)
                c = re.sub(r"([a-z])([A-Z])", r"\1 \2", c)
                clean_cells.append(c.strip())
            cleaned_rows.append(clean_cells)

        col_count = len(cleaned_rows[0])
        header = "| " + " | ".join(cleaned_rows[0]) + " |"
        separator = "| " + " | ".join(["---"] * col_count) + " |"
        body = ["| " + " | ".join(r[:col_count] + [""] * max(0, col_count - len(r))) + " |" for r in cleaned_rows[1:]]

        return "\n".join([header, separator] + body)

    @classmethod
    def _get_cached_ocr(cls, file_path: Path, page_idx: int) -> Optional[str]:
        """Check OCR cache directory for scanned document text."""
        ocr_dir = Path(OCR_CACHE_DIR)
        if not ocr_dir.exists():
            return None

    @classmethod
    def _ocr_page_fallback(cls, page: pymupdf.Page, file_path: Path, page_idx: int) -> str:
        """Fallback dynamic OCR using Gemini Vision if cache is absent."""
        try:
            from config.app_config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                return ""
            from google import genai
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    "Perform exact OCR on this scanned document image. Output the exact text, preserving all paragraphs, bullet points, headers, and metadata in Markdown.",
                    genai.types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                ],
            )
            extracted_text = resp.text.strip()
            if extracted_text:
                ocr_dir = Path(OCR_CACHE_DIR)
                ocr_dir.mkdir(parents=True, exist_ok=True)
                cache_target = ocr_dir / f"{file_path.stem}_p{page_idx}.txt"
                cache_target.write_text(extracted_text, encoding="utf-8")
                return extracted_text
        except Exception as ocr_err:
            logger.warning("OCR fallback failed for %s p%d: %s", file_path.name, page_idx, ocr_err)
        return ""

        # 1. Check doc-specific OCR cache file
        stem = file_path.stem
        candidates = [
            ocr_dir / f"{stem}_p{page_idx}.txt",
            ocr_dir / f"{stem}.txt",
        ]
        for c in candidates:
            if c.exists():
                try:
                    return c.read_text(encoding="utf-8")
                except Exception:
                    pass

        # 2. Check hash-based OCR cache files
        for p in ocr_dir.glob("*.txt"):
            if stem.lower() in p.name.lower():
                try:
                    return p.read_text(encoding="utf-8")
                except Exception:
                    pass

        return None

    @classmethod
    def _ocr_page_fallback(cls, page: pymupdf.Page, file_path: Path, page_idx: int) -> str:
        """Fallback dynamic OCR using Gemini Vision if cache is absent."""
        try:
            from config.app_config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                return ""
            from google import genai
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    "Perform exact OCR on this scanned document image. Output the exact text, preserving all paragraphs, bullet points, headers, and metadata in Markdown.",
                    genai.types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                ],
            )
            extracted_text = resp.text.strip()
            if extracted_text:
                ocr_dir = Path(OCR_CACHE_DIR)
                ocr_dir.mkdir(parents=True, exist_ok=True)
                cache_target = ocr_dir / f"{file_path.stem}_p{page_idx}.txt"
                cache_target.write_text(extracted_text, encoding="utf-8")
                return extracted_text
        except Exception as ocr_err:
            logger.warning("OCR fallback failed for %s p%d: %s", file_path.name, page_idx, ocr_err)
        return ""

    @classmethod
    def _parse_docx(cls, file_path: Path, manifest: ManifestEntry) -> str:
        """Extract text and tables from Word DOCX document."""
        doc = docx.Document(file_path)
        parts: List[str] = []

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            style_name = p.style.name.lower() if p.style else ""
            if "heading 1" in style_name:
                parts.append(f"# {text}")
            elif "heading 2" in style_name:
                parts.append(f"## {text}")
            elif "heading 3" in style_name:
                parts.append(f"### {text}")
            else:
                parts.append(text)

        for table in doc.tables:
            matrix: List[List[str]] = []
            for row in table.rows:
                matrix.append([cell.text.strip() for cell in row.cells])
            if matrix:
                md_tab = cls._matrix_to_markdown_table(matrix)
                if md_tab:
                    parts.append(md_tab)

        return "\n\n".join(parts)

    @classmethod
    def _parse_html(cls, file_path: Path, manifest: ManifestEntry) -> str:
        """Extract text and tables from HTML document using BeautifulSoup."""
        soup = bs4.BeautifulSoup(file_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        parts: List[str] = []

        for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "table", "li"]):
            if elem.name == "h1":
                parts.append(f"# {elem.get_text().strip()}")
            elif elem.name == "h2":
                parts.append(f"## {elem.get_text().strip()}")
            elif elem.name in ("h3", "h4"):
                parts.append(f"### {elem.get_text().strip()}")
            elif elem.name == "table":
                matrix: List[List[str]] = []
                for tr in elem.find_all("tr"):
                    cells = tr.find_all(["th", "td"])
                    matrix.append([c.get_text().strip() for c in cells])
                if matrix:
                    md_tab = cls._matrix_to_markdown_table(matrix)
                    if md_tab:
                        parts.append(md_tab)
            elif elem.name == "li":
                parts.append(f"- {elem.get_text().strip()}")
            else:
                text = elem.get_text().strip()
                if text:
                    parts.append(text)

        return "\n\n".join(parts)

    @classmethod
    def _markdown_to_sections(cls, markdown_text: str, manifest: ManifestEntry) -> List[DocumentSection]:
        """Split Markdown text into sections based on headers while preserving inline tables."""
        sections: List[DocumentSection] = []
        heading_regex = re.compile(r"^(#{1,4}\s+.+)$", re.MULTILINE)
        parts = heading_regex.split(markdown_text)

        current_locator = manifest.title
        for idx in range(len(parts)):
            part = parts[idx].strip()
            if not part:
                continue
            if heading_regex.match(part):
                current_locator = part.lstrip("#").strip()
            else:
                sections.append(DocumentSection(locator=current_locator, content=part))

        if not sections:
            sections.append(DocumentSection(locator=manifest.title, content=markdown_text))

        return sections
