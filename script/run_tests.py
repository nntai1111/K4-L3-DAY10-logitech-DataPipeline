from __future__ import annotations

import sys

import pytest

# One-click test run: the whole suite plus a coverage report for src/, failing below 80%.
# Tests use LLM_PROVIDER=mock inside a temporary project, so they are offline and never touch data/.
if __name__ == "__main__":
    sys.exit(pytest.main(["--cov=src", "--cov-report=term-missing", "--cov-fail-under=80", *sys.argv[1:]]))
