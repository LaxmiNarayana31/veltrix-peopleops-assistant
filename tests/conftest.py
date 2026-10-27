# 1. Python standard library
# (None)

# 2. Third-party installed packages
import pytest

# 3. Code-level (our own) imports
from app.core.lifespan import set_service_ready
from app.helper.llm.embedding_helper import FakeEmbeddingService, EmbeddingService
from app.helper.llm.llm_helper import FakeLLMProvider, LlmGateway
from config.database import get_db_manager


@pytest.fixture(autouse=True, scope="session")
def setup_test_suite_defaults():
    """Ensure entire test suite runs offline using fake embedding and LLM providers."""
    set_service_ready(True)
    get_db_manager().init_extra_tables()
    EmbeddingService.set_service(FakeEmbeddingService())
    LlmGateway.set_provider(FakeLLMProvider())
