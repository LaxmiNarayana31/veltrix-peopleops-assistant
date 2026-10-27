import os

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from datetime import date
from typing import List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv(verbose=True)

# API Credentials & Secrets
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")

# Optional LLM_PROVIDER: if not provided or empty, defaults directly to "gemini".
# Configurable to "gemini" or "groq" based on environment / system configuration.
_raw_provider: str = (os.getenv("LLM_PROVIDER") or "").strip().lower()
if _raw_provider in ("groq",):
    LLM_PROVIDER: str = "groq"
elif _raw_provider in ("gemini", "google"):
    LLM_PROVIDER: str = "gemini"
else:
    # Unset, empty, or unspecified defaults directly to gemini
    LLM_PROVIDER: str = "gemini"

# Qdrant Vector DB Configuration
# If QDRANT_URL is set, connects to remote/cloud instance (with optional QDRANT_API_KEY).
# If empty, defaults to local Docker container at http://localhost:6333
QDRANT_URL: Optional[str] = os.getenv("QDRANT_URL")
QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY")

# Helper for auto-discovering asset paths across data/, custom mounted dirs, or veltrix_assessment/
DATA_DIR_ENV: Optional[str] = os.getenv("DATA_DIR")


def _ensure_data_dir_synced() -> None:
    """If ./data/manifest.json does not exist, but veltrix_assessment is present, auto-populate ./data."""
    if os.path.exists("./data/manifest.json"):
        return
    candidates = [
        "./veltrix_assessment/veltrix_assessment",
        "./veltrix_assessment",
        "/app/veltrix_assessment/veltrix_assessment",
        "/app/veltrix_assessment",
    ]
    for cand in candidates:
        if os.path.exists(os.path.join(cand, "manifest.json")):
            try:
                import shutil
                os.makedirs("./data", exist_ok=True)
                for item in os.listdir(cand):
                    s = os.path.join(cand, item)
                    d = os.path.join("./data", item)
                    if not os.path.exists(d):
                        if os.path.isdir(s):
                            shutil.copytree(s, d)
                        else:
                            shutil.copy2(s, d)
                break
            except Exception:
                pass


_ensure_data_dir_synced()


def _find_existing_path(env_var: str, candidates: List[str], default: str) -> str:
    # 1. Check direct environment variable override
    env_val = os.getenv(env_var)
    if env_val and (os.path.exists(env_val) or os.path.isabs(env_val)):
        return env_val

    # 2. Check candidates
    for path in candidates:
        if path and (os.path.exists(path) or os.path.isabs(path) and os.path.exists(path)):
            return path

    return default


def _discover_manifest_path() -> str:
    # 1. Direct env override
    env_val = os.getenv("MANIFEST_PATH")
    if env_val and (os.path.exists(env_val) or os.path.isabs(env_val)):
        return env_val

    # 2. DATA_DIR env override
    if DATA_DIR_ENV:
        candidate = os.path.join(DATA_DIR_ENV, "manifest.json")
        if os.path.exists(candidate) or os.path.isabs(candidate):
            return candidate

    # 3. Known standard candidate paths
    standard_candidates = [
        "/app/data/manifest.json",
        "./data/manifest.json",
        "data/manifest.json",
        "./veltrix_assessment/manifest.json",
        "./veltrix_assessment/veltrix_assessment/manifest.json",
        "/app/veltrix_assessment/manifest.json",
        "/app/veltrix_assessment/veltrix_assessment/manifest.json",
        "manifest.json",
    ]
    for path in standard_candidates:
        if os.path.exists(path):
            return path

    # 4. Dynamic directory walk to locate any folder containing manifest.json
    try:
        for root, dirs, files in os.walk("."):
            if any(skip in root for skip in (".venv", ".git", "__pycache__", ".pytest_cache")):
                continue
            if "manifest.json" in files:
                return os.path.normpath(os.path.join(root, "manifest.json"))
    except Exception:
        pass

    return "./data/manifest.json"


# Storage & File System Paths (Auto-discovers ./data, /app/data, DATA_DIR, or custom directories)
MANIFEST_PATH: str = _discover_manifest_path()
_base_data_dir = os.path.dirname(MANIFEST_PATH) or (DATA_DIR_ENV if DATA_DIR_ENV and os.path.exists(DATA_DIR_ENV) else "./data")
os.makedirs(_base_data_dir, exist_ok=True)

CORPUS_DIR: str = _find_existing_path(
    "CORPUS_DIR",
    [
        os.path.join(_base_data_dir, "corpus"),
        os.path.join(DATA_DIR_ENV, "corpus") if DATA_DIR_ENV else "",
        "/app/data/corpus",
        "./data/corpus",
        "./veltrix_assessment/corpus",
        "./veltrix_assessment/veltrix_assessment/corpus",
        "/app/veltrix_assessment/corpus",
        "corpus",
    ],
    os.path.join(_base_data_dir, "corpus"),
)


def _discover_db_path() -> str:
    # 1. Direct env override
    env_db = os.getenv("DB_PATH")
    if env_db and (os.path.exists(env_db) or os.path.isabs(env_db)):
        return env_db

    # 2. Check candidates
    candidates = [
        os.path.join(_base_data_dir, "veltrix.db"),
        os.path.join(DATA_DIR_ENV, "veltrix.db") if DATA_DIR_ENV else "",
        "/app/data/veltrix.db",
        "./data/veltrix.db",
        "./veltrix_assessment/veltrix.db",
        "./veltrix_assessment/veltrix_assessment/veltrix.db",
        "/app/veltrix_assessment/veltrix.db",
        "veltrix.db",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c

    # 3. Check for any .db or .sqlite file in _base_data_dir
    try:
        if os.path.exists(_base_data_dir):
            for fname in os.listdir(_base_data_dir):
                if fname.endswith((".db", ".sqlite", ".sqlite3")):
                    return os.path.normpath(os.path.join(_base_data_dir, fname))
    except Exception:
        pass

    return os.path.join(_base_data_dir, "veltrix.db")


DB_PATH: str = _discover_db_path()

OCR_CACHE_DIR: str = os.path.join(_base_data_dir, "ocr_cache")
EMBEDDING_CACHE_DB_PATH: str = os.path.join(_base_data_dir, "embedding_cache.sqlite")
CHUNKS_CACHE_PATH: str = os.path.join(_base_data_dir, "chunks_cache.json")
LOG_FILE_PATH: str = "./logs/server_logs.log"

# Reference Date & Calendar Constants
_app_today_env = os.getenv("APP_TODAY")
if _app_today_env and _app_today_env.strip():
    REFERENCE_DATE: date = date.fromisoformat(_app_today_env.strip())
    APP_TODAY: str = _app_today_env.strip()
else:
    REFERENCE_DATE: date = date.today()
    APP_TODAY: str = REFERENCE_DATE.isoformat()
DEFAULT_REFERENCE_DATE: date = REFERENCE_DATE

# LLM & Embedding Models
GEMINI_PRIMARY_MODEL: str = "gemini-3.1-flash-lite"
GEMINI_FALLBACK_MODEL: str = "gemini-2.5-flash-lite"
GROQ_PRIMARY_MODEL: str = "openai/gpt-oss-120b"
GROQ_FALLBACK_MODEL: str = "qwen/qwen3.8-27b"
GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

if LLM_PROVIDER == "groq" and GROQ_API_KEY:
    LLM_FALLBACK_CHAIN: List[Tuple[str, str]] = [
        ("groq", GROQ_PRIMARY_MODEL),
        ("groq", GROQ_FALLBACK_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
    ]
else:
    LLM_FALLBACK_CHAIN: List[Tuple[str, str]] = [
        ("gemini", GEMINI_PRIMARY_MODEL),
        ("gemini", GEMINI_FALLBACK_MODEL),
    ]
    if GROQ_API_KEY:
        LLM_FALLBACK_CHAIN.extend([
            ("groq", GROQ_PRIMARY_MODEL),
            ("groq", GROQ_FALLBACK_MODEL),
        ])

# Operational Budgets & Limits
REQUEST_TIMEOUT_SECONDS: int = 25
CORPUS_TOKEN_BUDGET: int = 3000


def validate_api_configuration() -> bool:
    """Validate presence of compulsory GEMINI_API_KEY and display actionable guidance if missing."""
    if not GEMINI_API_KEY:
        banner = (
            "\n"
            + "=" * 74 + "\n"
            "  [WARNING] COMPULSORY GEMINI_API_KEY NOT CONFIGURED!\n"
            "  GEMINI_API_KEY is compulsory because it powers corpus embeddings\n"
            "  (gemini-embedding-001) and primary assistant policy reasoning.\n"
            "  (Note: GROQ_API_KEY is optional for alternative response generation)\n\n"
            "  Please supply your Gemini API key:\n"
            "    1. In a .env file in the project root:\n"
            "         cp .env.example .env\n"
            "         GEMINI_API_KEY=your_gemini_api_key\n\n"
            "    2. Or pass it externally:\n"
            "         docker compose --env-file /path/to/.env up --build\n"
            "         docker run -e GEMINI_API_KEY=your_key -p 8000:8000 ...\n"
            + "=" * 74 + "\n"
        )
        print(banner, flush=True)
        return False
    return True


