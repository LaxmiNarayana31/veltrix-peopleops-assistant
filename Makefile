.PHONY: test run lint clean

test:
	uv run pytest -v

run:
	uv run uvicorn main:app --host 0.0.0.0 --port 8000

lint:
	uv run python -m py_compile main.py

clean:
	rm -rf .pytest_cache __pycache__ data/qdrant
