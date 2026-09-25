"""End to end: phase 1, then the corruption flow twice, against a throwaway project directory.

One module-scoped fixture runs the whole thing once (real ChromaDB, real MiniLM, mock LLM judge);
every test below only reads the artifacts it left behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import load_settings
from core.utils import read_json
from pipelines import corruption_flow, phase1

REPO_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow

EXPECTED_CORRUPTED_FAILURES = {
    "expect_column_values_to_be_unique(paper_id)",
    "expect_column_value_lengths_to_be_between(title)",
    "expect_column_value_lengths_to_be_between(summary)",
    "expect_column_values_to_not_match_regex(summary)",
}


def _real_data_fingerprint() -> dict[str, tuple[int, int]]:
    data_dir = REPO_ROOT / "data"
    return {str(path.relative_to(data_dir)): (path.stat().st_size, path.stat().st_mtime_ns) for path in data_dir.rglob("*") if path.is_file()}


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory, make_project, apply_env, run_date):
    real_data_before = _real_data_fingerprint()
    with pytest.MonkeyPatch.context() as patcher:
        apply_env(patcher, run_date=run_date)
        settings = load_settings(make_project(tmp_path_factory.mktemp("e2e_project")))
        patcher.setattr(phase1, "load_settings", lambda: settings)
        patcher.setattr(corruption_flow, "load_settings", lambda: settings)

        phase1.main()
        repair_log = settings.paths.project_dir / "data" / "results" / "repair_idempotency.json"
        corruption_flow.main()
        first_repair = read_json(repair_log)
        corruption_flow.main()
        second_repair = read_json(repair_log)

    yield {
        "settings": settings,
        "paths": settings.paths,
        "first_repair": first_repair,
        "second_repair": second_repair,
        "real_data_before": real_data_before,
    }


def test_settings_point_at_the_temp_project(pipeline_run):
    paths = pipeline_run["paths"]
    assert not paths.project_dir.is_relative_to(REPO_ROOT)
    assert pipeline_run["settings"].llm_provider == "mock"
    assert pipeline_run["settings"].run_date == "2026-09-25"


def test_real_data_folder_is_untouched(pipeline_run):
    assert _real_data_fingerprint() == pipeline_run["real_data_before"]


def test_phase1_artifacts_exist(pipeline_run):
    paths = pipeline_run["paths"]
    for path in (
        paths.raw_api_response,
        paths.raw_records_json,
        paths.clean_csv,
        paths.clean_json,
        paths.embeddings_json,
        paths.eval_testset,
        paths.baseline_quality_report,
        paths.freshness_report,
        paths.baseline_metrics,
        paths.baseline_answers,
        paths.demo_answers,
        paths.run_context,
        paths.baseline_report,
    ):
        assert path.is_file(), path


def test_corruption_flow_artifacts_exist(pipeline_run):
    paths = pipeline_run["paths"]
    for path in (
        paths.corrupted_clean_csv,
        paths.corrupted_clean_json,
        paths.corrupted_embeddings_json,
        paths.corrupted_quality_report,
        paths.quality_dir / "corrupted_freshness_report.json",
        paths.quality_dir / "repaired_quality_report.json",
        paths.quality_dir / "repaired_freshness_report.json",
        paths.corruption_log,
        paths.corrupted_metrics,
        paths.corrupted_answers,
        paths.repaired_clean_csv,
        paths.repaired_clean_json,
        paths.repaired_embeddings_json,
        paths.repaired_metrics,
        paths.repaired_answers,
        paths.comparison_report,
    ):
        assert path.is_file(), path


def test_run_context(pipeline_run):
    context = read_json(pipeline_run["paths"].run_context)
    assert context["run_date"] == "2026-09-25"
    assert context["source_mode"] == "snapshot"
    assert (context["raw_records"], context["clean_rows"], context["test_set_size"]) == (24, 24, 10)
    assert context["llm_provider"] == "mock"


def test_baseline_passes_the_gate_and_scores_perfectly(pipeline_run):
    paths = pipeline_run["paths"]
    quality = read_json(paths.baseline_quality_report)
    metrics = read_json(paths.baseline_metrics)
    assert quality["success"] is True and quality["gate_passed"] is True
    assert metrics["samples"] == 10
    assert metrics["retrieval_hit_rate"] == 1.0
    assert metrics["mean_token_f1"] == 1.0


def test_mock_judge_and_skipped_agent_demo(pipeline_run):
    paths = pipeline_run["paths"]
    answers = read_json(paths.baseline_answers)
    assert all(answer["judge"]["reasoning"].startswith("Fallback heuristic judge") for answer in answers)
    assert "skipped" in read_json(paths.demo_answers)[0]


def test_manifests_are_portable(pipeline_run):
    paths = pipeline_run["paths"]
    for manifest_path, collection in (
        (paths.embeddings_json, "papers-baseline"),
        (paths.corrupted_embeddings_json, "papers-corrupted"),
        (paths.repaired_embeddings_json, "papers-repaired"),
    ):
        manifest = read_json(manifest_path)
        assert manifest["persist_path"] == "data/chroma"
        assert manifest["collection_name"] == collection


def test_corrupted_batch_fails_the_gate(pipeline_run):
    paths = pipeline_run["paths"]
    quality = read_json(paths.corrupted_quality_report)
    assert quality["row_count"] == 24
    assert quality["success"] is False
    assert set(quality["failed_expectations"]) == EXPECTED_CORRUPTED_FAILURES
    assert quality["freshness"]["is_fresh"] is False
    assert quality["gate_passed"] is False
    assert read_json(paths.corruption_log)["scenario_count"] == 6


def test_corruption_hurts_retrieval(pipeline_run):
    paths = pipeline_run["paths"]
    baseline = read_json(paths.baseline_metrics)
    corrupted = read_json(paths.corrupted_metrics)
    assert corrupted["retrieval_hit_rate"] < baseline["retrieval_hit_rate"]
    assert corrupted["mean_token_f1"] < baseline["mean_token_f1"]


def test_repair_restores_baseline_metrics(pipeline_run):
    paths = pipeline_run["paths"]
    assert read_json(paths.repaired_metrics) == read_json(paths.baseline_metrics)
    repaired_quality = read_json(paths.quality_dir / "repaired_quality_report.json")
    assert repaired_quality["success"] is True and repaired_quality["gate_passed"] is True


def test_repaired_table_is_byte_identical_to_baseline(pipeline_run):
    paths = pipeline_run["paths"]
    assert paths.repaired_clean_json.read_bytes() == paths.clean_json.read_bytes()
    assert paths.repaired_clean_csv.read_bytes() == paths.clean_csv.read_bytes()


def test_repair_is_idempotent(pipeline_run):
    first, second = pipeline_run["first_repair"], pipeline_run["second_repair"]
    context = read_json(pipeline_run["paths"].run_context)
    assert first["repaired_matches_baseline"] is True
    assert first["repaired_sha256"] == first["baseline_sha256"] == context["baseline_sha256"]
    assert first["auto_triggered"] is True
    assert first["matches_previous_run"] is None
    assert second["repaired_matches_baseline"] is True
    assert second["previous_repaired_sha256"] == first["repaired_sha256"]
    assert second["matches_previous_run"] is True


def test_reports_render(pipeline_run):
    paths = pipeline_run["paths"]
    phase1_text = Path(paths.baseline_report).read_text(encoding="utf-8")
    comparison_text = Path(paths.comparison_report).read_text(encoding="utf-8")
    assert "# Báo cáo Pha 1" in phase1_text and "## 5. Artifact đã sinh" in phase1_text
    for heading in ("## 1. Kết luận nhanh", "## 4. Sáu kịch bản tiêm lỗi", "## 5. Từng câu hỏi", "## 6. Idempotent repair"):
        assert heading in comparison_text
    assert "trùng lần chạy trước" in comparison_text
