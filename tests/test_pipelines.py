from __future__ import annotations

from dataclasses import replace

from langchain_core.messages import AIMessage
import pytest

from core.utils import read_json
from observability.reporting import METRIC_KEYS
from pipelines import common, corruption_flow, phase1
from retrieval import agent as agent_module
from retrieval.index import LocalEmbeddingIndex

from conftest import ToolCallingFakeModel


@pytest.fixture
def pipelines_on(settings, monkeypatch):
    monkeypatch.setattr(phase1, "load_settings", lambda: settings)
    monkeypatch.setattr(corruption_flow, "load_settings", lambda: settings)
    return settings


def test_phase1_and_corruption_flow_end_to_end(pipelines_on, capsys):
    settings = pipelines_on
    paths = settings.paths
    phase1.main()
    corruption_flow.main()

    expected = [
        paths.raw_records_json, paths.clean_csv, paths.clean_json, paths.baseline_quality_report, paths.freshness_report,
        paths.embeddings_json, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers, paths.demo_answers,
        paths.baseline_report, paths.corruption_log, paths.corrupted_clean_csv, paths.corrupted_quality_report,
        paths.corrupted_metrics, paths.corrupted_answers, paths.repaired_clean_csv, paths.repaired_metrics,
        paths.repaired_answers, paths.comparison_report, paths.corrupted_embeddings_json, paths.repaired_embeddings_json,
    ]
    assert [path.name for path in expected if not path.exists()] == []

    baseline, corrupted, repaired = (read_json(path) for path in (paths.baseline_metrics, paths.corrupted_metrics, paths.repaired_metrics))
    assert baseline["retrieval_hit_rate"] == 1.0 and baseline["mean_token_f1"] == 1.0
    assert corrupted["retrieval_hit_rate"] < baseline["retrieval_hit_rate"]
    assert corrupted["mean_token_f1"] < baseline["mean_token_f1"]
    assert {key: repaired[key] for key in METRIC_KEYS} == {key: baseline[key] for key in METRIC_KEYS}
    assert corrupted["state"] == "corrupted" and corrupted["collection"] == "papers-corrupted"

    assert read_json(paths.baseline_quality_report)["success"] is True
    assert read_json(paths.corrupted_quality_report)["success"] is False
    assert read_json(paths.quality_dir / "repaired_quality_report.json")["success"] is True
    assert read_json(paths.quality_dir / "corrupted_freshness_report.json")["is_fresh"] is False

    repair_log = read_json(paths.corruption_log.parent / "repair_log.json")
    assert repair_log["idempotent"] and repair_log["matches_baseline"] and repair_log["lineage_verified"]
    assert repair_log["trigger"]["gate_failed"] is True

    demo = read_json(paths.demo_answers)
    assert len(demo) == 3  # the mock LLM cannot call tools, so errors are recorded instead of crashing
    assert "Bảng đối chiếu 3 trạng thái" in paths.comparison_report.read_text(encoding="utf-8")
    assert "Data quality gate" in paths.baseline_report.read_text(encoding="utf-8")

    output = capsys.readouterr().out
    assert "quality_gate" in output and "Hoàn tất pha 2." in output

    # Rerunning phase 1 reuses the fixed benchmark instead of regenerating it.
    before = paths.eval_testset.read_text(encoding="utf-8")
    phase1.main()
    assert paths.eval_testset.read_text(encoding="utf-8") == before
    assert "tái sử dụng bộ cố định" in capsys.readouterr().out


def test_phase1_blocks_indexing_when_the_gate_fails(pipelines_on, monkeypatch, capsys):
    failing = {"success": False, "failed_checks": ["paper_id_unique"], "statistics": {"successful_expectations": 11, "evaluated_expectations": 12}}
    monkeypatch.setattr(phase1, "run_data_quality_checks", lambda df, settings, name: failing)
    with pytest.raises(SystemExit):
        phase1.main()
    assert not pipelines_on.paths.embeddings_json.exists()
    assert "Không index dữ liệu xấu" in capsys.readouterr().out


def test_phase1_can_skip_the_agent_demo(pipelines_on, monkeypatch):
    monkeypatch.setenv("SKIP_AGENT_DEMO", "1")
    phase1.main()
    assert read_json(pipelines_on.paths.demo_answers) == []


def test_corruption_flow_requires_phase1_artifacts(pipelines_on, capsys):
    with pytest.raises(SystemExit):
        corruption_flow.main()
    assert "run_phase1.py" in capsys.readouterr().out


def test_agent_demo_collects_answers_and_errors(settings, clean_df, monkeypatch):
    index = LocalEmbeddingIndex.build(clean_df, settings, settings.paths.embeddings_json)
    test_set = [
        {"question_type": "summary", "question": "Q summary"},
        {"question_type": "authors", "question": "Q authors"},
    ]
    script = iter([AIMessage(content=[{"type": "text", "text": "first"}]), AIMessage(content="second")])
    monkeypatch.setattr(agent_module, "build_llm", lambda settings, temperature: ToolCallingFakeModel(messages=script))
    demo = phase1.run_agent_demo(settings, index, test_set)
    assert [item.get("answer") for item in demo[:2]] == ["first", "second"]
    assert "error" in demo[2]  # the scripted model ran out of replies

    def broken(settings, index):
        raise RuntimeError(f"bad key {settings.google_api_key}")

    monkeypatch.setattr(phase1, "build_agent", broken)
    secret_settings = replace(settings, google_api_key="SECRET-123")
    errors = phase1.run_agent_demo(secret_settings, index, test_set)
    assert all("SECRET-123" not in item["error"] and "***" in item["error"] for item in errors)


def test_redact_hides_every_configured_key(settings):
    secret_settings = replace(settings, openai_api_key="sk-abc", anthropic_api_key="ant-xyz")
    assert common.redact("sk-abc and ant-xyz", secret_settings) == "*** and ***"
