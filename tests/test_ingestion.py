# 1. Python standard library
# (None)

# 2. Third-party installed packages
import pytest

# 3. Code-level (our own) imports
from app.helper.ingestion.ingestion_helper import IngestionService
from app.helper.llm.embedding_helper import EmbeddingService, FakeEmbeddingService
from config.database import get_db_connection, get_db_manager


@pytest.fixture(scope="module", autouse=True)
def setup_ingestion_env():
    """Ensure offline fake embeddings are used during tests to protect API limits."""
    EmbeddingService.set_service(FakeEmbeddingService())
    get_db_manager().init_extra_tables()


def test_ingestion_pipeline_end_to_end():
    """Verify that ingestion processes the corpus, extracts holidays, chunks text, and indexes data."""
    IngestionService.run_ingestion()

    # 1. Verify chunks generated
    chunks = IngestionService.get_all_chunks()
    assert len(chunks) > 50, f"Expected > 50 chunks, got {len(chunks)}"

    # 2. Verify BM25 index built
    bm25 = IngestionService.get_bm25_index()
    assert bm25 is not None

    # 3. Verify Qdrant collection has records
    point_count = IngestionService.get_collection_count()
    assert point_count == len(chunks)

    # 4. Verify holidays table populated from calendar docs
    conn = get_db_connection()
    try:
        holiday_rows = conn.execute("SELECT region, date, name, source_doc_id FROM holidays").fetchall()
        assert len(holiday_rows) > 10, f"Expected > 10 holidays, found {len(holiday_rows)}"
        regions_with_holidays = {r["region"] for r in holiday_rows}
        assert "IN" in regions_with_holidays
        assert "US" in regions_with_holidays
        assert "DE" in regions_with_holidays
    finally:
        conn.close()

    # 5. Verify scanned memo was OCR'd and chunked
    memo_chunks = [c for c in chunks if "MEMO" in c.doc_id or "hybrid" in c.text.lower()]
    assert len(memo_chunks) > 0, "Expected OCR'd memo chunks to be present in indexed corpus"
    assert any("Chief People Officer" in c.text or "hybrid" in c.text.lower() for c in memo_chunks)
