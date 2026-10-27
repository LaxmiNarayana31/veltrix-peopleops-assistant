# Veltrix PeopleOps Assistant

AI HR assistant for Veltrix Systems. Answers company policy questions with deterministic Section 5 document precedence, manages leave requests through a two-step confirmation workflow, and enforces role-based access control and employee privacy.

> For architectural details and system flow diagrams, see [DESIGN.md](DESIGN.md).

---

## 1. Quickstart

### Method A: Docker (Recommended)

1. **Clone the repository:**
   ```bash
   git clone <your-repository-url>
   cd veltrix-peopleops-assistant
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and set your `GEMINI_API_KEY` (see [Section 2: Environment Variables](#2-environment-variables)).

3. **Start services:**
   ```bash
   docker compose up --build
   ```
   * Qdrant vector database runs on `http://localhost:6333`
   * API server runs on `http://localhost:8000`
   * All policy corpus documents are indexed automatically on startup (~3 seconds).

4. **Verify health:**
   ```bash
   curl http://localhost:8000/health
   # Returns: {"status": "ok"}
   ```

5. **Send a test query:**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Employee-Id: E2004" \
     -d '{"session_id": "test_01", "message": "What is the annual leave allowance for employees in India?"}'
   ```
   Interactive Swagger documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

### Method B: Local Setup (Without Docker)

1. **Prerequisites:** Python 3.12 and [uv](https://github.com/astral-sh/uv).

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and set your `GEMINI_API_KEY` (see [Section 2: Environment Variables](#2-environment-variables)).

4. **Start the application:**
   ```bash
   uv run main.py
   ```
   The service will start locally on `http://localhost:8000`.

5. **Run test suite (optional):**
   ```bash
   uv run pytest -v
   ```

---

## 2. Environment Variables

Create `.env` in the project root:

```ini
CORPUS_DIR=./data/corpus
MANIFEST_PATH=./data/manifest.json
DB_PATH=./data/veltrix.db

QDRANT_URL=
QDRANT_API_KEY=

APP_TODAY=2026-10-20
LLM_PROVIDER=gemini

# Compulsory (required for reasoning and embeddings)
GEMINI_API_KEY=your_gemini_api_key_here

# Optional (only needed if using Groq)
GROQ_API_KEY=
```

> **Data Directory:** The system automatically checks `./data` and `./veltrix_assessment` for the policy documents, manifest, and database. To specify a custom location, set `DATA_DIR=/path/to/data`.

---

## 3. Architectural Assumptions

1. **Uniform Permission Refusal:** Requests attempting to view records of other employees are refused with a standard message: `"I can't share information about that employee."` This prevents inferring whether an employee exists.
2. **Policy Conflict Handling:** When two valid documents from the same authority level, region, and effective date provide conflicting terms, both rules and their respective citations are presented with a conflict notice.
3. **Scanned Document Extraction:** Scanned pages without embedded digital text use pre-processed text caching with vision model fallback.
4. **Regional Calendar Precedence:** Public holidays are evaluated dynamically for each region based on policies active on the effective reference date.

---

## 4. Known Limitations

1. **In-Memory Session Storage:** Active chat sessions and pending leave proposals are stored in process memory. Multi-server production deployments would use a distributed cache such as Redis.
2. **Calendar Boundary:** Leave balance accruals and working day calculations are configured for the 2026 calendar year.
