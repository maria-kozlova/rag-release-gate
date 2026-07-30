# For reviewers and ubuntu-latest CI. `make` does not exist in PowerShell —
# the documented local path on Windows is `uv run` or .\tasks.ps1.

.PHONY: help sync unit live lint fmt ingest evaluate report clean

help:
	@echo "sync      install the exact locked environment"
	@echo "unit      unit checks (NOT the release gate) - no key, no network"
	@echo "live      THE RELEASE GATE - costs money, requires OPENROUTER_API_KEY"
	@echo "lint      ruff check"
	@echo "fmt       ruff format"
	@echo "ingest    build data/index/ from the corpus"
	@echo "evaluate  one live run (default scope: smoke)"
	@echo "report    render the latest run to reports/"

sync:
	uv sync --locked

unit:
	uv run pytest -m "not live"

live:
	uv run pytest -m live

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

ingest:
	uv run python -m rag_release_gate.ingest

evaluate:
	uv run python -m rag_release_gate.cli evaluate --scope smoke

report:
	uv run python -m rag_release_gate.cli report

clean:
	rm -rf .pytest_cache .ruff_cache data/index/index.npz
