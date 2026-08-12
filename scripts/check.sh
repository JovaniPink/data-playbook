#!/usr/bin/env bash
set -euo pipefail

uv lock --check
uv sync --all-groups --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pip-audit
