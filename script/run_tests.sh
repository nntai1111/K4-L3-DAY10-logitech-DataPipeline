#!/usr/bin/env bash
# One-click test run: the whole pytest suite plus a line-by-line coverage report for src/.
#
#   bash script/run_tests.sh                 # everything (about a minute)
#   bash script/run_tests.sh -m "not slow"   # skip the ChromaDB/MiniLM tests
#
# Extra arguments are passed straight to pytest. The suite never touches the real data/ folder,
# needs no API key (the LLM judge runs in mock mode), and works offline once the MiniLM model is
# in the Hugging Face cache.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTEST_ARGS=(--cov=src --cov-report=term-missing -q "$@")

if command -v uv >/dev/null 2>&1; then
  # --no-sync matters: a plain `uv run` first syncs .venv to uv.lock, and on machines where Windows
  # Application Control blocks some wheels (scikit-learn 1.9.0) that breaks the environment.
  # pytest and pytest-cov are layered on top of the existing .venv for this run only.
  exec uv run --no-sync --with pytest --with pytest-cov pytest "${PYTEST_ARGS[@]}"
fi

for python in .venv/Scripts/python.exe .venv/bin/python; do
  if [ -x "$python" ]; then
    if ! "$python" -c "import pytest, pytest_cov" >/dev/null 2>&1; then
      echo "pytest/pytest-cov missing from .venv. Install them with:" >&2
      echo "  $python -m pip install pytest pytest-cov" >&2
      exit 1
    fi
    exec "$python" -m pytest "${PYTEST_ARGS[@]}"
  fi
done

echo "Neither uv nor a .venv was found. Create the environment first (see README)." >&2
exit 1
