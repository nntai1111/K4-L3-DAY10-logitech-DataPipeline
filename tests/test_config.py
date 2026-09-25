"""Settings, small utilities, and the pipeline helpers that do not need an index."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from core.config import load_settings, normalized_provider, require_llm_credentials
from core.utils import compact_join, first_sentence, normalize_whitespace, safe_slug
from pipelines import common, corruption_flow, phase1

# --- core.config -------------------------------------------------------------------------------


def test_every_data_path_is_rooted_in_the_project(settings, project_dir):
    paths = settings.paths
    assert paths.project_dir == project_dir.resolve()
    assert paths.workspace_dir == project_dir.resolve().parent
    for name, value in vars(paths).items():
        if name not in {"project_dir", "workspace_dir"}:
            assert value.is_relative_to(project_dir.resolve() / "data"), name


def test_defaults(settings):
    assert settings.llm_provider == "mock"
    assert settings.model_name == "gemini-2.5-flash"
    assert settings.max_results == 24 and settings.top_k == 4
    assert settings.freshness_threshold_days == 180
    assert settings.refresh_source is False and settings.refresh_test_set is False
    assert settings.run_date is None
    assert settings.source_filter.startswith("from-pub-date:") and settings.source_filter.endswith(",has-abstract:true")


def test_environment_overrides(project_dir, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("REFRESH_TEST_SET", "true")
    monkeypatch.setenv("RUN_DATE", "2026-09-25")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:1")
    settings = load_settings(project_dir)
    assert (settings.model_name, settings.refresh_test_set, settings.run_date, settings.ollama_base_url) == ("m", True, "2026-09-25", "http://ollama:1")


def test_project_env_file_fills_unset_variables_only(project_dir, monkeypatch):
    (project_dir / ".env").write_text("LLM_MODEL=from-dotenv\nLLM_PROVIDER=gemini\n", encoding="utf-8")
    # set-then-delete makes monkeypatch remember LLM_MODEL as originally absent, so the value
    # load_dotenv writes into os.environ is removed again after the test.
    monkeypatch.setenv("LLM_MODEL", "placeholder")
    monkeypatch.delenv("LLM_MODEL")
    settings = load_settings(project_dir)
    assert settings.model_name == "from-dotenv"
    assert settings.llm_provider == "mock", "a variable already set in the environment wins over .env"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Gemini", "gemini"), ("Open AI", "openai"), ("anthorpic", "anthropic"), ("custom-llm", "custom"), ("CustomLLM", "custom"), (" mock ", "mock")],
)
def test_normalized_provider(settings, raw, expected):
    assert normalized_provider(replace(settings, llm_provider=raw)) == expected


@pytest.mark.parametrize(
    ("provider", "field", "message"),
    [
        ("gemini", "google_api_key", "GOOGLE_API_KEY"),
        ("openai", "openai_api_key", "OPENAI_API_KEY"),
        ("anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("openrouter", "openrouter_api_key", "OPENROUTER_API_KEY"),
        ("custom", "custom_llm_base_url", "CUSTOM_LLM_BASE_URL"),
    ],
)
def test_require_llm_credentials(settings, provider, field, message):
    configured = replace(settings, llm_provider=provider)
    with pytest.raises(RuntimeError, match=message):
        require_llm_credentials(configured)
    require_llm_credentials(replace(configured, **{field: "set"}))


@pytest.mark.parametrize("provider", ["mock", "ollama"])
def test_keyless_providers_need_no_credentials(settings, provider):
    require_llm_credentials(replace(settings, llm_provider=provider))


def test_unknown_provider_is_rejected(settings):
    with pytest.raises(RuntimeError, match="Unsupported LLM_PROVIDER"):
        require_llm_credentials(replace(settings, llm_provider="watson"))


# --- core.utils --------------------------------------------------------------------------------


def test_small_text_helpers():
    assert normalize_whitespace("  a \n\t b  ") == "a b"
    assert safe_slug("Hello, World!") == "hello-world"
    assert safe_slug("***") == "item"
    assert compact_join(["a", "", "b"]) == "a, b"
    assert first_sentence("One. Two? Three!") == "One."
    assert first_sentence("  no   terminal punctuation ") == "no terminal punctuation"


# --- pipelines.common --------------------------------------------------------------------------


def test_choose_run_date(settings):
    assert common.choose_run_date(replace(settings, run_date="2026-09-25")) == date(2026, 9, 25)
    assert common.choose_run_date(settings) == common.now_utc().date()


def test_load_run_context_requires_phase1(settings):
    with pytest.raises(SystemExit, match="run_phase1"):
        common.load_run_context(settings)


def test_table_hash_survives_a_save_and_reload(clean_df, settings):
    common.save_table(clean_df, settings.paths.clean_csv, settings.paths.clean_json)
    assert settings.paths.clean_csv.exists()
    reloaded = common.read_table(settings.paths.clean_json)
    assert common.table_sha256(reloaded) == common.table_sha256(clean_df)


def test_table_hash_ignores_index_but_not_content(clean_df):
    baseline = common.table_sha256(clean_df)
    assert common.table_sha256(clean_df.set_axis(range(100, 124))) == baseline
    edited = clean_df.copy()
    edited.loc[0, "title"] += "!"
    assert common.table_sha256(edited) != baseline
    assert common.table_sha256(clean_df.iloc[::-1]) != baseline, "row order is part of the contract"


def test_relative_paths(settings):
    assert common.relative(settings, settings.paths.clean_csv) == "data/clean/papers_clean.csv"


def test_configure_logging_quiets_noisy_libraries():
    import logging

    common.configure_logging()
    assert logging.getLogger("chromadb").level == logging.WARNING


# --- pipeline guards that stop before any index is built ---------------------------------------


def test_phase1_blocks_indexing_when_the_gate_fails(settings, monkeypatch):
    monkeypatch.setattr(phase1, "load_settings", lambda: settings)
    monkeypatch.setattr(
        phase1,
        "run_data_quality_checks",
        lambda df, settings, name: {"success": False, "failed_expectations": ["expect_x"], "freshness": {"is_fresh": True}},
    )
    monkeypatch.setattr(phase1.LocalEmbeddingIndex, "build", lambda *args, **kwargs: pytest.fail("must not index a failed batch"))
    with pytest.raises(SystemExit, match="blocked indexing.*expect_x"):
        phase1.main()
    assert settings.paths.clean_json.exists()


def test_corruption_flow_requires_phase1(settings, monkeypatch):
    monkeypatch.setattr(corruption_flow, "load_settings", lambda: settings)
    with pytest.raises(SystemExit, match="run_context.json is missing"):
        corruption_flow.main()


# --- phase1 agent demo -------------------------------------------------------------------------


def test_agent_demo_is_skipped_for_mock_or_when_disabled(settings, monkeypatch):
    monkeypatch.setattr(phase1, "build_agent", lambda *a: pytest.fail("agent must not be built"))
    assert "skipped" in phase1._run_agent_demo(settings, index=None)[0]
    monkeypatch.setenv("RUN_AGENT_DEMO", "1")
    assert "skipped" in phase1._run_agent_demo(settings, index=None)[0]
    monkeypatch.setenv("RUN_AGENT_DEMO", "false")
    assert "skipped" in phase1._run_agent_demo(replace(settings, llm_provider="openai"), index=None)[0]


def test_agent_demo_answers_and_records_errors(settings, monkeypatch):
    monkeypatch.setenv("RUN_AGENT_DEMO", "1")
    live = replace(settings, llm_provider="openai")
    answers = iter(["first answer", RuntimeError("rate limited " + "x" * 400)])

    def fake_run(agent, question):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(phase1, "build_agent", lambda settings, index: "agent")
    monkeypatch.setattr(phase1, "run_agent_question", fake_run)
    result = phase1._run_agent_demo(live, index=None)

    assert result[0] == {"question": phase1.AGENT_DEMO_QUESTIONS[0], "answer": "first answer"}
    assert result[1]["question"] == phase1.AGENT_DEMO_QUESTIONS[1]
    assert result[1]["error"].startswith("rate limited") and len(result[1]["error"]) == 300


def test_agent_demo_stringifies_non_text_answers(settings, monkeypatch):
    monkeypatch.setenv("RUN_AGENT_DEMO", "1")
    monkeypatch.setattr(phase1, "build_agent", lambda settings, index: "agent")
    monkeypatch.setattr(phase1, "run_agent_question", lambda agent, question: [{"type": "text", "text": "hi"}])
    result = phase1._run_agent_demo(replace(settings, llm_provider="openai"), index=None)
    assert result[0]["answer"] == "[{'type': 'text', 'text': 'hi'}]"


def test_agent_demo_reports_a_build_failure(settings, monkeypatch):
    monkeypatch.setenv("RUN_AGENT_DEMO", "1")

    def broken_build(settings, index):
        raise RuntimeError("OPENAI_API_KEY is required")

    monkeypatch.setattr(phase1, "build_agent", broken_build)
    [result] = phase1._run_agent_demo(replace(settings, llm_provider="openai"), index=None)
    assert result == {"error": "Agent could not be built: OPENAI_API_KEY is required"}
