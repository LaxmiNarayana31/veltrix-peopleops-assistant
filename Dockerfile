FROM python:3.12-slim

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    LLM_PROVIDER=gemini

# Copy dependency specifications and lockfile
COPY pyproject.toml uv.lock README.md ./

# Install project dependencies
RUN uv sync --frozen --no-dev

# Copy application source code
COPY app/ ./app/
COPY config/ ./config/
COPY main.py ./

# Copy baseline data directory (volume mount can override at runtime)
COPY data/ ./data/

# Create logs directory
RUN mkdir -p /app/logs && chmod 777 /app/logs

# Expose HTTP port
EXPOSE 8000

# Start server
CMD ["uv", "run", "main.py"]
