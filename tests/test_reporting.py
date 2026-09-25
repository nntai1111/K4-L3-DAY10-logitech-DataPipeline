from __future__ import annotations

from observability.reporting import (
    _cell,
    _code,
    _delta,
    _recovery,
    format_comparison_table,
    generate_corruption_report,
    generate_phase1_report,
    summarize_answers,
)


def _answer(question_type, hit, f1, correct, reasoning="LLM verdict"):
    return {"question_type": question_type, "retrieval_hit": hit, "token_f1": f1, "judge": {"correct": correct, "reasoning": reasoning}}


def test_summarize_answers_breaks_down_types_and_judge_sources():
    answers = [
        _answer("summary", True, 1.0, True),
        _answer("summary", False, 0.0, False, "Fallback heuristic judge used because ..."),
        _answer("date", True, 0.5, True),
        {**_answer("date", True, 1.0, True), "judge_source": "exact_match"},
        {**_answer("authors", True, 0.7, True), "judge_source": "cache"},
    ]
    summary = summarize_answers(answers)
    assert summary["by_question_type"]["summary"] == {"samples": 2, "retrieval_hit_rate": 0.5, "mean_token_f1": 0.5, "judge_accuracy": 0.5}
    assert summary["judge_mode"] == {"llm": 2, "llm_cached": 1, "exact_match": 1, "fallback_heuristic": 1}


def test_formatting_helpers():
    assert _delta(0.8, 1.0) == "-0.200"
    assert _delta("n/a", 1.0) == "—"
    assert _recovery(1.0, 0.8, 1.0) == "100%"
    assert _recovery(1.0, 0.8, 0.9) == "50%"
    assert _recovery(1.0, 1.0, 1.0) == "không suy giảm"
    assert _recovery(None, 1.0, 1.0) == "—"
    assert _cell("a|b\nc") == "a\\|b c"
    assert _code("x" * 100, limit=10) == "`xxxxxxx...`"
    assert _code("") == '`""`'


def _quality(success, failed=()):
    expectations = [
        {"check_id": "paper_id_unique", "expectation": "expect_column_values_to_be_unique", "dimension": "uniqueness", "required": True,
         "success": "paper_id_unique" not in failed, "unexpected_count": 2 if "paper_id_unique" in failed else 0, "element_count": 10,
         "unexpected_examples": ["10.1/a"] if "paper_id_unique" in failed else []},
        {"check_id": "source_papers_present", "expectation": "expect_column_distinct_values_to_contain_set", "dimension": "completeness",
         "required": False, "success": "source_papers_present" not in failed, "observed_value": "9/10 source papers present",
         "missing_count": 1 if "source_papers_present" in failed else 0, "missing_examples": ["10.1/z"]},
        {"check_id": "row_count", "expectation": "expect_table_row_count_to_be_between", "dimension": "volume", "required": True,
         "success": "row_count" not in failed, "observed_value": 3},
    ]
    passed = sum(entry["success"] for entry in expectations)
    return {"success": success, "failed_checks": list(failed), "expectations": expectations, "row_count": 10, "unique_paper_ids": 9,
            "statistics": {"evaluated_expectations": 3, "successful_expectations": passed, "success_percent": 100 * passed / 3},
            "engine": "great_expectations test", "gx_validation_result": "data/quality/gx/x.json"}


def _freshness(is_fresh, latest="2026-07-22"):
    return {"is_fresh": is_fresh, "status": "FRESH" if is_fresh else "STALE", "stale_rows": 1 if is_fresh else 4, "total_rows": 10,
            "stale_ratio": 0.1 if is_fresh else 0.4, "threshold_days": 180, "max_stale_ratio": 0.25, "latest_published": latest,
            "oldest_published": "2025-01-01", "newest_age_days": 65, "median_age_days": 100.0, "oldest_age_days": 400, "message": "m"}


def _metrics(hit, f1, fallback=0):
    return {"samples": 2, "retrieval_hit_rate": hit, "mean_token_f1": f1, "judge_accuracy": hit, "mean_judge_score": 4.0,
            "llm": "gemini/test", "judge_mode": {"llm": 2 - fallback, "fallback_heuristic": fallback}, "ragas": {"error": "boom"},
            "by_question_type": {"summary": {"samples": 2, "retrieval_hit_rate": hit, "mean_token_f1": f1, "judge_accuracy": hit}}}


def test_phase1_report_renders_demo_errors_and_non_perfect_metrics(tmp_path):
    path = tmp_path / "phase1.md"
    source = {
        "generated_at": "now",
        "ingestion": {"mode": "snapshot_fallback", "fallback_reason": "ConnectionError"},
        "cleaning": {"rules": ["rule one"]},
        "agent_demo": [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": None, "error": "RateLimit"}],
        "artifacts": [("Clean CSV", "data/clean/papers_clean.csv")],
    }
    generate_phase1_report(path, source, _metrics(0.5, 0.4, fallback=1), _quality(False, ("row_count",)), _freshness(False))
    text = path.read_text(encoding="utf-8")
    assert "❌ FAIL (2/3)" in text and "⚠️ STALE" in text
    assert "lý do fallback: ConnectionError" in text
    assert "**Lỗi:** `RateLimit`" in text and "**Đáp:** a1" in text
    assert "heuristic fallback" in text
    assert "Diễn giải" not in text  # the upper-bound note only appears for a perfect baseline


def test_corruption_report_links_events_to_questions_and_detection(tmp_path):
    path = tmp_path / "corruption.md"
    log = {
        "seed": 42, "input_rows": 10, "output_rows": 11, "unique_papers": 9,
        "corruptions": [
            {"step": 1, "type": "drop_latest_records", "description": "d", "parameters": {"fraction": 0.2}, "affected_rows": 1,
             "paper_ids": ["10.1/z"], "detected_by": ["source_papers_present", "freshness.latest_published"], "examples": [{"paper_id": "10.1/z"}]},
            {"step": 2, "type": "duplicate_rows", "description": "d", "parameters": {}, "affected_rows": 1,
             "paper_ids": ["10.1/a"], "detected_by": ["paper_id_unique"], "examples": [{"paper_id": "10.1/a"}]},
            {"step": 3, "type": "truncate_title", "description": "d", "parameters": {}, "affected_rows": 1,
             "paper_ids": ["10.1/q"], "detected_by": ["title_min_length"], "examples": [{"before": "Long title", "after": "Long"}]},
        ],
    }
    answers = {
        "baseline": [
            {"id": "eval_001", "question_type": "summary", "question": "What is 'Z paper'?", "ground_truth_doc_ids": ["10.1/z"], "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
            {"id": "eval_002", "question_type": "authors", "question": "Who authored 'A paper'?", "ground_truth_doc_ids": ["10.1/a"], "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
            {"id": "eval_003", "question_type": "date", "question": "When was 'B paper' published?", "ground_truth_doc_ids": ["10.1/b"], "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
        ],
        "corrupted": [
            {"id": "eval_001", "retrieval_hit": False, "token_f1": 0.7, "judge": {"correct": True}},
            {"id": "eval_002", "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
            {"id": "eval_003", "retrieval_hit": True, "token_f1": 0.5, "judge": {"correct": True}},
        ],
        "repaired": [
            {"id": "eval_001", "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
            {"id": "eval_002", "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
            {"id": "eval_003", "retrieval_hit": True, "token_f1": 1.0, "judge": {"correct": True}},
        ],
    }
    repair = {"generated_at": "now", "source": "data/raw/crossref_records.json", "lineage_reference": "data/raw/crossref_response.json",
              "lineage_verified": True, "idempotent": True, "matches_baseline": True,
              "trigger": {"failed_checks": ["paper_id_unique"], "freshness_status": "STALE"},
              "fingerprints": {"baseline_clean": "a" * 64, "corrupted": "b" * 64, "repair_run_1": "a" * 64, "repair_run_2": "a" * 64},
              "artifacts": [("Repair log", "data/results/repair_log.json")]}
    generate_corruption_report(
        path, _metrics(1.0, 1.0), _metrics(0.5, 0.55), _metrics(1.0, 1.0),
        _quality(False, ("paper_id_unique", "source_papers_present")), _quality(True), _freshness(False, "2026-06-01"), _freshness(True),
        baseline_quality=_quality(True), baseline_freshness=_freshness(True), corruption_log=log, answers=answers, repair=repair,
    )
    text = path.read_text(encoding="utf-8")
    assert "## 1. Bảng đối chiếu 3 trạng thái" in text
    assert "| `retrieval_hit_rate` | 1.000 | 0.500 | 1.000 | -0.500 | +0.000 | 100% |" in text
    assert "✅ `source_papers_present`, `freshness.latest_published`" in text
    assert "mất retrieval hit ở 1 câu (eval_001)" in text
    assert "câu trả lời không đổi" in text  # duplicate rows did not change eval_002
    assert "Truncate title** (1 dòng): không trúng tài liệu nào" in text
    assert "Hiệu ứng gián tiếp:** eval_003" in text
    assert "Silent failure nguy hiểm nhất:** eval_001" in text

    table = format_comparison_table(_metrics(1.0, 1.0), _metrics(0.5, 0.55), _metrics(1.0, 1.0), (None, _quality(False), _quality(True)), (_freshness(True), _freshness(False), None))
    lines = table.splitlines()
    assert lines[0].split() == ["Metric", "Baseline", "Corrupted", "Repaired"]
    assert "FAIL" in table and "STALE 40%" in table and "—" in table
