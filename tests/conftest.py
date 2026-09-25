"""Shared fixtures for the pipeline test suite.

Every test runs against a throwaway project directory under pytest's tmp_path that holds a copy
of the two committed raw snapshots, so no test ever writes into the real data/ folder. The LLM
judge is forced to the offline mock provider, and the run date is pinned so age-based checks
give the same answer no matter which day the suite runs.
"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_RAW_DIR = REPO_ROOT / "data" / "raw"
RAW_FILES = ("crossref_response.json", "crossref_records.json")
FIXED_RUN_DATE = date(2026, 9, 25)
MINILM_CACHE_NAME = "models--sentence-transformers--all-MiniLM-L6-v2"

# Environment variables the pipeline reads. They are cleared per test so a value exported in the
# developer's shell (REFRESH_SOURCE=1, a real API key, ...) cannot change what a test observes.
PIPELINE_ENV_VARS = (
    "REFRESH_SOURCE",
    "CROSSREF_MAILTO",
    "REFRESH_TEST_SET",
    "RUN_DATE",
    "RUN_RAGAS",
    "LLM_MODEL",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "CUSTOM_LLM_API_KEY",
    "CUSTOM_LLM_BASE_URL",
)


def _minilm_is_cached() -> bool:
    hf_home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    hub_cache = Path(os.environ.get("HF_HUB_CACHE") or hf_home / "hub")
    return (hub_cache / MINILM_CACHE_NAME / "snapshots").is_dir()


# Set before huggingface_hub is imported: with the model already cached, skip the online
# freshness check so the suite is fast and works without a network. A fresh CI runner has no
# cache yet, so there the model is downloaded once and cached by the workflow.
if _minilm_is_cached():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")


def copy_raw_snapshots(project_dir: Path) -> Path:
    raw_dir = project_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in RAW_FILES:
        shutil.copyfile(REAL_RAW_DIR / name, raw_dir / name)
    return project_dir


def apply_offline_env(patcher: pytest.MonkeyPatch, run_date: date | None = None) -> None:
    for name in PIPELINE_ENV_VARS:
        patcher.delenv(name, raising=False)
    patcher.setenv("LLM_PROVIDER", "mock")
    patcher.setenv("RUN_AGENT_DEMO", "0")
    if run_date is not None:
        patcher.setenv("RUN_DATE", run_date.isoformat())


@pytest.fixture(autouse=True)
def offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_offline_env(monkeypatch)


@pytest.fixture(scope="session")
def run_date() -> date:
    return FIXED_RUN_DATE


@pytest.fixture(scope="session")
def raw_payload() -> dict[str, Any]:
    return json.loads((REAL_RAW_DIR / "crossref_response.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def committed_records() -> list[dict[str, Any]]:
    return json.loads((REAL_RAW_DIR / "crossref_records.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def make_project() -> Callable[[Path], Path]:
    """Factory for module-scoped fixtures that need their own project directory."""
    return copy_raw_snapshots


@pytest.fixture(scope="session")
def apply_env() -> Callable[..., None]:
    """The offline environment, for module-scoped fixtures that run under MonkeyPatch.context()."""
    return apply_offline_env


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return copy_raw_snapshots(tmp_path)


@pytest.fixture
def settings(project_dir: Path):
    from core.config import load_settings

    return load_settings(project_dir)


@pytest.fixture
def records(settings):
    from ingestion.crossref import load_raw_records

    return load_raw_records(settings.paths.raw_records_json)


@pytest.fixture
def clean_df(records, run_date):
    from ingestion.cleaning import build_clean_dataframe

    return build_clean_dataframe(records, run_date)


@pytest.fixture
def make_search_result() -> Callable[[dict[str, Any]], Any]:
    """Turn one clean-table row into the SearchResult the index would return for it."""
    from retrieval.index import SearchResult

    def build(row: dict[str, Any], score: float = 0.5) -> SearchResult:
        return SearchResult(
            paper_id=row["paper_id"],
            title=row["title"],
            score=score,
            content=row["text_for_embedding"],
            metadata={
                "paper_id": row["paper_id"],
                "title": row["title"],
                "published": row["published"],
                "authors_joined": row["authors_joined"],
                "categories_joined": row["categories_joined"],
                "summary": row["summary"],
                "abs_url": row["abs_url"],
                "pdf_url": row["pdf_url"],
            },
        )

    return build


class FakeIndex:
    """Stands in for LocalEmbeddingIndex without Chroma or the embedding model.

    `search` returns the rows in table order (or the fixed list it was given), and `lookup`
    matches paper_id or title case-insensitively, like the real index.
    """

    def __init__(self, rows: list[dict[str, Any]], make_result, search_results: list | None = None):
        self.rows = rows
        self.make_result = make_result
        self.search_results = search_results
        self.search_calls: list[tuple[str, int | None]] = []

    def search(self, query: str, top_k: int | None = None):
        self.search_calls.append((query, top_k))
        if self.search_results is not None:
            return list(self.search_results)
        return [self.make_result(row) for row in self.rows[: top_k or 4]]

    def lookup(self, value: str):
        needle = value.strip().lower()
        for row in self.rows:
            if needle in {row["paper_id"].lower(), row["title"].lower()}:
                result = self.make_result(row)
                return {
                    "paper_id": result.paper_id,
                    "title": result.title,
                    "content": result.content,
                    "metadata": result.metadata,
                }
        return None


@pytest.fixture
def make_fake_index(clean_df, make_search_result) -> Callable[..., FakeIndex]:
    def build(rows: list[dict[str, Any]] | None = None, search_results: list | None = None) -> FakeIndex:
        return FakeIndex(clean_df.to_dict(orient="records") if rows is None else rows, make_search_result, search_results)

    return build


@pytest.fixture
def fake_index(make_fake_index) -> FakeIndex:
    return make_fake_index()
