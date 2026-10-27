# 1. Python standard library
from datetime import date

# 2. Third-party installed packages
import pytest

# 3. Code-level (our own) imports
from app.dto.chat_dto import RequestContext
from app.exceptions.custom_exceptions import TokenBudgetExceededException
from app.helper.access.access_helper import AccessService
from app.helper.ingestion.ingestion_helper import IngestionService
from app.helper.llm.embedding_helper import EmbeddingService, FakeEmbeddingService
from app.helper.llm.llm_helper import FakeLLMProvider, LlmGateway
from app.helper.retrieval.retrieval_helper import RetrievalService
from app.utils.constants import MAX_CORPUS_TOKENS_BUDGET, UserRole
from app.utils.token_counter import TokenCounter


@pytest.fixture(scope="module", autouse=True)
def setup_services():
    """Initialize test environment with fake offline embedding and LLM providers."""
    EmbeddingService.set_service(FakeEmbeddingService())
    IngestionService.run_ingestion()
    LlmGateway.set_provider(FakeLLMProvider())


def test_document_eligibility_by_role_and_region():
    """Verify role-based and regional pre-filtering rules."""
    ref_date = date(2026, 6, 1)

    # 1. Standard employee in IN
    emp_in = RequestContext(
        employee_id="E2001",
        role=UserRole.EMPLOYEE,
        region="IN",
        full_name="Standard Employee",
        email="e***@veltrix.example",
    )
    eligible_in, _ = AccessService.eligible_doc_ids(emp_in, ref_date)

    for doc_id in eligible_in:
        entry = AccessService.get_manifest_entry(doc_id)
        assert entry is not None
        # Must be accessible to 'all'
        assert entry.access_level == "all", f"Employee received restricted doc {doc_id} with access {entry.access_level}"
        # Must be GLOBAL or IN
        assert "GLOBAL" in entry.regions or "IN" in entry.regions, f"Employee received foreign region doc {doc_id}: {entry.regions}"
        assert "US" not in entry.regions or "GLOBAL" in entry.regions
        assert "DE" not in entry.regions or "GLOBAL" in entry.regions

    # 2. Manager in US
    mgr_us = RequestContext(
        employee_id="M1001",
        role=UserRole.MANAGER,
        region="US",
        full_name="Manager US",
        email="m***@veltrix.example",
    )
    eligible_mgr, _ = AccessService.eligible_doc_ids(mgr_us, ref_date)

    for doc_id in eligible_mgr:
        entry = AccessService.get_manifest_entry(doc_id)
        assert entry is not None
        assert entry.access_level in ("all", "managers")
        assert "GLOBAL" in entry.regions or "US" in entry.regions

    # 3. HR in DE
    hr_de = RequestContext(
        employee_id="H1001",
        role=UserRole.HR,
        region="DE",
        full_name="HR DE",
        email="h***@veltrix.example",
    )
    eligible_hr, _ = AccessService.eligible_doc_ids(hr_de, ref_date)

    for doc_id in eligible_hr:
        entry = AccessService.get_manifest_entry(doc_id)
        assert entry is not None
        assert entry.access_level in ("all", "managers", "hr")
        assert "GLOBAL" in entry.regions or "DE" in entry.regions


def test_retrieval_pre_filter_and_token_budget():
    """Verify retrieval results never contain restricted docs and respect token limits."""
    emp_ctx = RequestContext(
        employee_id="E2001",
        role=UserRole.EMPLOYEE,
        region="IN",
        full_name="Standard Employee",
        email="e***@veltrix.example",
    )

    res = RetrievalService.retrieve(emp_ctx, query="What is the leave policy and hybrid work allowance?")

    # Verify token budget packing <= 3000 tokens
    assert res.total_tokens <= MAX_CORPUS_TOKENS_BUDGET
    corpus_text = "\n\n".join(c.text for c in res.all_chunks)
    actual_tokens = TokenCounter.count_tokens(corpus_text)
    assert actual_tokens <= MAX_CORPUS_TOKENS_BUDGET

    # Verify no restricted docs in retrieval chunks
    for chunk in res.all_chunks:
        entry = AccessService.get_manifest_entry(chunk.doc_id)
        assert entry is not None
        assert entry.access_level == "all"
        assert "GLOBAL" in entry.regions or "IN" in entry.regions


def test_llm_gateway_guards_corpus_token_budget():
    """Verify LLM gateway raises TokenBudgetExceededException when corpus text exceeds 3000 tokens."""
    # Generate text guaranteed to exceed 3000 tokens
    large_corpus_text = "Policy document clause with extensive regulatory details and leave policy guidelines. " * 400
    assert TokenCounter.count_tokens(large_corpus_text) > 3000

    with pytest.raises(TokenBudgetExceededException, match="exceeds maximum allowed budget"):
        LlmGateway.execute_call(
            request_id="req_test_guard",
            call_purpose="test_budget_overflow",
            system="System instruction",
            user="User query",
            corpus_text=large_corpus_text,
        )
