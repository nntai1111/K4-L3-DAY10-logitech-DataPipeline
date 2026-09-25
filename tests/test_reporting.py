from __future__ import annotations

import pytest

from core.utils import read_json
from ingestion.corruption import corrupt_clean_dataframe
from observability import reporting
from observability.quality import run_data_quality_checks

JUDGE_FALLBACK = {"score": 5, "correct": True, "reasoning": reporting.FALLBACK_JUDGE_PREFIX + " used because ..."}
JUDGE_LLM = {"score": 4, "correct": True, "reasoning": "Matches the reference."}


def _metrics(hit: float, f1: float) -> dict:
    return {"samples": 2, "retrieval_hit_rate": hit, "mean_token_f1": f1, "judge_accuracy": hit, "mean_judge_score": 5 * hit}


def _answers(doc_ids: list[str], hits: list[bool], judge: dict) -> list[dict]:
    return [
        {
            "id": f"eval_{number:03d}",
            "question_type": "summary" if number % 2 else "authors",
            "ground_truth_doc_ids": [doc_id],
            "retrieval_hit": hit,
            "token_f1": 1.0 if hit else 0.0,
            "judge": judge,
        }
        for number, (doc_id, hit) in enumerate(zip(doc_ids, hits, strict=True), start=1)
    ]


@pytest.fixture
def gate_reports(clean_df, settings):
    corrupted_df = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    return {
        "baseline": run_data_quality_checks(clean_df, settings, "baseline"),
        "corrupted": run_data_quality_checks(corrupted_df, settings, "corrupted"),
        "repaired": run_data_quality_checks(clean_df, settings, "repaired"),
        "log": read_json(settings.paths.corruption_log),
    }


def test_phase1_report_renders_every_section(tmp_path, gate_reports):
    baseline = gate_reports["baseline"]
    answers = _answers(["10.1/a", "10.1/b"], [True, True], JUDGE_FALLBACK)
    answers[1]["judge"] = JUDGE_LLM
    path = tmp_path / "reports" / "phase1.md"

    reporting.generate_phase1_report(
        path,
        source_summary={
            "run_date": "2026-09-25",
            "source_api": "Crossref REST API",
            "source_mode": "snapshot",
            "source_query": "q",
            "source_filter": "f",
            "raw_records": 24,
            "clean_rows": 24,
            "embedding_model": "m",
            "collection_name": "papers-baseline",
            "top_k": 4,
            "llm_provider": "mock",
            "llm_model": "x",
            "artifacts": ["data/clean/papers_clean.csv", "data/eval/test_set.json"],
        },
        metrics=_metrics(1.0, 1.0),
        quality=baseline,
        freshness=baseline["freshness"],
        answers=answers,
    )
    text = path.read_text(encoding="utf-8")

    for heading in ("# Báo cáo Pha 1", "## 1. Nguồn dữ liệu", "## 2. Chỉ số", "## 3. Quality gate", "## 4. Freshness SLA", "## 5. Artifact"):
        assert heading in text
    assert "`run_date` = **2026-09-25**" in text
    assert "| Retrieval hit rate | 1.000 |" in text
    assert "| Verdict do LLM chấm / heuristic dự phòng | 1 / 1 |" in text
    assert "| summary | 1 | 1.000 | 1.000 |" in text
    assert "Kết quả GX: **PASS** — 8/8" in text
    assert "`expect_column_values_to_be_unique(paper_id)` | required | PASS" in text
    assert "- `data/eval/test_set.json`" in text
    assert "Tươi" in text


def test_phase1_report_without_answers(tmp_path, gate_reports):
    stale = dict(gate_reports["baseline"]["freshness"], is_fresh=False)
    path = tmp_path / "phase1.md"
    reporting.generate_phase1_report(
        path,
        source_summary={
            key: "x"
            for key in ("run_date", "source_api", "source_mode", "source_query", "source_filter", "raw_records", "clean_rows", "embedding_model", "collection_name", "top_k", "llm_provider", "llm_model")
        },
        metrics=_metrics(0.5, 0.25),
        quality=gate_reports["baseline"],
        freshness=stale,
    )
    text = path.read_text(encoding="utf-8")
    assert "| Verdict do LLM chấm / heuristic dự phòng | 0 / 0 |" in text
    assert "Quá hạn" in text


def test_corruption_report_renders_every_section(tmp_path, gate_reports):
    log = gate_reports["log"]
    by_name = {scenario["scenario"]: scenario for scenario in log["scenarios"]}
    doc_ids = [by_name["drop_latest_records"]["paper_ids"][0], by_name["truncate_title"]["paper_ids"][0]]
    path = tmp_path / "corruption.md"

    reporting.generate_corruption_report(
        path,
        baseline_metrics=_metrics(1.0, 1.0),
        corrupted_metrics=_metrics(0.5, 0.4),
        repaired_metrics=_metrics(1.0, 1.0),
        corrupted_quality=gate_reports["corrupted"],
        repaired_quality=gate_reports["repaired"],
        corrupted_freshness=gate_reports["corrupted"]["freshness"],
        repaired_freshness=gate_reports["repaired"]["freshness"],
        baseline_quality=gate_reports["baseline"],
        corruption_log=log,
        answers_by_state={
            "baseline": _answers(doc_ids, [True, True], JUDGE_FALLBACK),
            "corrupted": _answers(doc_ids, [False, False], JUDGE_FALLBACK),
            "repaired": _answers(doc_ids, [True, True], JUDGE_LLM),
        },
        repair={
            "source": "data/raw/crossref_records.json",
            "run_date": "2026-09-25",
            "collection": "papers-repaired",
            "auto_triggered": True,
            "baseline_sha256": "a" * 64,
            "repaired_sha256": "a" * 64,
            "repaired_matches_baseline": True,
            "previous_repaired_sha256": "a" * 64,
            "matches_previous_run": True,
        },
    )
    text = path.read_text(encoding="utf-8")

    for heading in ("## 1. Kết luận nhanh", "## 2. Chỉ số RAG", "## 3. Quality gate", "## 4. Sáu kịch bản", "## 5. Từng câu hỏi", "## 6. Idempotent repair"):
        assert heading in text
    assert "hit rate 1.00 → 0.50" in text
    assert "| Retrieval hit rate | 1.000 | 0.500 | 1.000 | -0.500 | 0.000 |" in text
    assert "| Verdict LLM / heuristic | 0 / 2 | 0 / 2 | 2 / 0 | — | — |" in text
    assert "GX FAIL trên dữ liệu bẩn (4 expectation fail)" in text
    for scenario in log["scenarios"]:
        assert f"| `{scenario['scenario']}` |" in text
    assert "`expect_column_values_to_be_unique(paper_id)` — đã bắt" in text
    assert "Freshness SLA — đã bắt" in text
    assert "Không expectation nào bắt được; chỉ lộ ra qua bài mới nhất" in text
    assert "| eval_001 | summary | drop_latest_records | ✓ / ✗ / ✓ |" in text
    assert "bảng sau repair trùng khớp bảng baseline" in text
    assert "trùng lần chạy trước" in text
    assert "tự động vì gate fail" in text
    assert "sha256 lần chạy trước" in text


def test_corruption_report_minimal_inputs(tmp_path, gate_reports):
    path = tmp_path / "corruption.md"
    reporting.generate_corruption_report(
        path,
        baseline_metrics=_metrics(1.0, 1.0),
        corrupted_metrics=_metrics(1.0, 1.0),
        repaired_metrics=_metrics(1.0, 1.0),
        corrupted_quality=gate_reports["corrupted"],
        repaired_quality=gate_reports["repaired"],
        corrupted_freshness=gate_reports["corrupted"]["freshness"],
        repaired_freshness=gate_reports["repaired"]["freshness"],
    )
    text = path.read_text(encoding="utf-8")
    assert "## 3. Quality gate và freshness" in text
    assert "| Expectation | Tầng | Corrupted | Repaired |" in text
    for absent in ("## 4.", "## 5.", "## 6.", "Idempotent:", "Verdict LLM"):
        assert absent not in text


def test_corruption_report_first_repair_has_no_previous_run(tmp_path, gate_reports):
    path = tmp_path / "corruption.md"
    reporting.generate_corruption_report(
        path,
        baseline_metrics=_metrics(1.0, 1.0),
        corrupted_metrics=_metrics(0.5, 0.5),
        repaired_metrics=_metrics(1.0, 1.0),
        corrupted_quality=gate_reports["corrupted"],
        repaired_quality=gate_reports["repaired"],
        corrupted_freshness=gate_reports["corrupted"]["freshness"],
        repaired_freshness=gate_reports["repaired"]["freshness"],
        corruption_log=gate_reports["log"],
        repair={
            "source": "s",
            "run_date": "2026-09-25",
            "collection": "c",
            "auto_triggered": False,
            "baseline_sha256": "a" * 64,
            "repaired_sha256": "b" * 64,
            "repaired_matches_baseline": False,
            "previous_repaired_sha256": None,
            "matches_previous_run": None,
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "bảng sau repair KHÁC bảng baseline" in text
    assert "lần chạy trước" not in text
    assert "thủ công" in text
    assert "| `drop_latest_records` | 4 |" in text and "Không expectation nào bắt được |" in text


# --- small helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "True"), (None, "None"), (1, "1.000"), (0.12345, "0.123"), ("text", "text")],
)
def test_format_number(value, expected):
    assert reporting._format_number(value) == expected


@pytest.mark.parametrize(
    ("current", "reference", "expected"),
    [(0.5, 1.0, "-0.500"), (1.0, 0.5, "+0.500"), (1.0, 1.0002, "0.000"), ("n/a", 1.0, "—"), (1.0, None, "—")],
)
def test_format_delta(current, reference, expected):
    assert reporting._format_delta(current, reference) == expected


def test_scenario_detector_edge_cases(gate_reports):
    corrupted = gate_reports["corrupted"]
    fresh_corrupted = dict(corrupted, freshness=dict(corrupted["freshness"], is_fresh=True))
    assert reporting._scenario_detected("stale_date", fresh_corrupted, None) == "Freshness SLA — KHÔNG bắt"
    assert reporting._scenario_detected("drop_latest_records", corrupted, None) == "Không expectation nào bắt được"
    assert "không có trong suite" in reporting._scenario_detected("blank_summary", dict(corrupted, expectations=[]), None)
    passing = dict(corrupted, expectations=[dict(item, success=True) for item in corrupted["expectations"]])
    assert reporting._scenario_detected("duplicate_rows", passing, None).endswith("KHÔNG bắt")


def test_every_scenario_has_a_detector_entry(gate_reports):
    assert {scenario["scenario"] for scenario in gate_reports["log"]["scenarios"]} == set(reporting.SCENARIO_DETECTORS)


def test_affected_questions():
    answers = _answers(["10.1/a", "10.1/b"], [True, True], JUDGE_LLM)
    assert reporting._affected_questions({"paper_ids": ["10.1/b"]}, answers) == ["eval_002"]
    assert reporting._affected_questions({"paper_ids": []}, answers) == []


def test_expectation_table_shows_observed_value_when_no_row_count(tmp_path, clean_df, settings, gate_reports):
    tiny = run_data_quality_checks(clean_df.head(3), settings, "tiny")
    lines = reporting._expectation_table({"corrupted": tiny, "repaired": gate_reports["repaired"]})
    [row_count_line] = [line for line in lines if "expect_table_row_count_to_be_between" in line]
    assert "FAIL (quan sát: 3)" in row_count_line and row_count_line.endswith("| PASS |")
