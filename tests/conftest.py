from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
import pytest

from core.config import load_settings
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import load_raw_records

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
RUN_DATE = datetime(2026, 9, 25, tzinfo=UTC)


class ToolCallingFakeModel(GenericFakeChatModel):
    """Scripted chat model that accepts tools, so the LangChain agent can run offline."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Settings rooted in a throw-away project holding a copy of the committed raw snapshot.

    The mock LLM keeps the suite offline and deterministic; real artifacts are never touched.
    """
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    for name in ("REFRESH_SOURCE", "REFRESH_TEST_SET", "RUN_RAGAS", "SKIP_AGENT_DEMO"):
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "project"
    shutil.copytree(RAW_DIR, project / "data" / "raw", ignore=shutil.ignore_patterns("archive", "ingestion_manifest.json"))
    return load_settings(project)


@pytest.fixture(scope="session")
def raw_records():
    return load_raw_records(RAW_DIR / "crossref_records.json")


@pytest.fixture
def clean_df(raw_records):
    return build_clean_dataframe(raw_records, RUN_DATE)
