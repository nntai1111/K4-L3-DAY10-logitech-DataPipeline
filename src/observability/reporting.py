from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from core.utils import now_utc, write_text

FALLBACK_JUDGE_PREFIX = "Fallback heuristic judge"
STATES = ("baseline", "corrupted", "repaired")
STATE_LABELS = {"baseline": "Baseline", "corrupted": "Corrupted", "repaired": "Repaired"}
METRIC_ROWS = [
    ("retrieval_hit_rate", "Retrieval hit rate"),
    ("mean_token_f1", "Mean token F1"),
    ("judge_accuracy", "Judge accuracy"),
    ("mean_judge_score", "Mean judge score (1–5)"),
]
# Which check is meant to catch each corruption scenario. The report reads the actual gate result
# rather than assuming the check fired.
SCENARIO_DETECTORS = {
    "drop_latest_records": None,
    "blank_summary": "expect_column_value_lengths_to_be_between(summary)",
    "inject_text_noise": "expect_column_values_to_not_match_regex(summary)",
    "truncate_title": "expect_column_value_lengths_to_be_between(title)",
    "stale_date": "freshness_sla",
    "duplicate_rows": "expect_column_values_to_be_unique(paper_id)",
}


def _format_number(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def _format_delta(current: Any, reference: Any) -> str:
    if not isinstance(current, (int, float)) or not isinstance(reference, (int, float)):
        return "—"
    delta = current - reference
    return "0.000" if abs(delta) < 5e-4 else f"{delta:+.3f}"


def _pass_fail(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def _expectation_key(item: dict[str, Any]) -> str:
    return f"{item['expectation']}({item['column']})" if item.get("column") else item["expectation"]


def _judge_modes(answers: list[dict[str, Any]]) -> tuple[int, int]:
    fallback = sum(1 for answer in answers if answer["judge"]["reasoning"].startswith(FALLBACK_JUDGE_PREFIX))
    return len(answers) - fallback, fallback


def _per_type_rows(answers: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for answer in answers:
        grouped[answer["question_type"]].append(answer)
    rows = []
    for question_type in sorted(grouped):
        items = grouped[question_type]
        hit_rate = mean(1.0 if item["retrieval_hit"] else 0.0 for item in items)
        token_f1 = mean(item["token_f1"] for item in items)
        rows.append(f"| {question_type} | {len(items)} | {hit_rate:.3f} | {token_f1:.3f} |")
    return rows


def _expectation_table(quality_by_state: dict[str, dict[str, Any]]) -> list[str]:
    states = [state for state in STATES if state in quality_by_state]
    lines = [
        "| Expectation | Tầng | " + " | ".join(STATE_LABELS[state] for state in states) + " |",
        "| --- | --- | " + " | ".join("---" for _ in states) + " |",
    ]
    first_state = quality_by_state[states[0]]
    by_key = {state: {_expectation_key(item): item for item in quality_by_state[state]["expectations"]} for state in states}
    for item in first_state["expectations"]:
        cells = []
        for state in states:
            state_item = by_key[state][_expectation_key(item)]
            detail = ""
            if not state_item["success"] and state_item.get("unexpected_count") is not None:
                detail = f" ({state_item['unexpected_count']} dòng lỗi)"
            elif not state_item["success"] and state_item.get("observed_value") is not None:
                detail = f" (quan sát: {state_item['observed_value']})"
            cells.append(_pass_fail(state_item["success"]) + detail)
        lines.append(f"| `{_expectation_key(item)}` | {item['tier']} | " + " | ".join(cells) + " |")
    freshness_cells = []
    for state in states:
        freshness = quality_by_state[state]["freshness"]
        freshness_cells.append(f"{_pass_fail(freshness['is_fresh'])} ({freshness['stale_rows']}/{freshness['total_rows']} dòng > {freshness['freshness_threshold_days']} ngày)")
    lines.append("| Freshness SLA (≤ 25% dòng quá hạn) | sla | " + " | ".join(freshness_cells) + " |")
    return lines


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
    answers: list[dict[str, Any]] | None = None,
) -> None:
    answers = answers or []
    llm_verdicts, fallback_verdicts = _judge_modes(answers)
    lines = [
        "# Báo cáo Pha 1 — Baseline",
        "",
        f"Sinh tự động bởi `script/run_phase1.py` lúc {now_utc().strftime('%Y-%m-%d %H:%M UTC')}. "
        f"`run_date` = **{source_summary['run_date']}** (mọi `age_days` tính theo ngày này).",
        "",
        "## 1. Nguồn dữ liệu",
        "",
        "| Thuộc tính | Giá trị |",
        "| --- | --- |",
        f"| Nguồn | {source_summary['source_api']} |",
        f"| Chế độ lấy dữ liệu | {source_summary['source_mode']} |",
        f"| Query | `{source_summary['source_query']}` |",
        f"| Filter | `{source_summary['source_filter']}` |",
        f"| Số record raw | {source_summary['raw_records']} |",
        f"| Số dòng sau làm sạch | {source_summary['clean_rows']} |",
        f"| Embedding model | `{source_summary['embedding_model']}` |",
        f"| ChromaDB collection | `{source_summary['collection_name']}` (top_k = {source_summary['top_k']}) |",
        f"| LLM judge | `{source_summary['llm_provider']}` / `{source_summary['llm_model']}` |",
        "",
        "## 2. Chỉ số đánh giá trên dữ liệu sạch",
        "",
        "| Chỉ số | Giá trị |",
        "| --- | --- |",
        f"| Số câu hỏi | {metrics['samples']} |",
    ]
    lines += [f"| {label} | {_format_number(metrics[key])} |" for key, label in METRIC_ROWS]
    lines += [
        f"| Verdict do LLM chấm / heuristic dự phòng | {llm_verdicts} / {fallback_verdicts} |",
        "",
        "Theo loại câu hỏi:",
        "",
        "| Loại | Số câu | Hit rate | Token F1 |",
        "| --- | ---: | ---: | ---: |",
        *_per_type_rows(answers),
        "",
        "## 3. Quality gate (Great Expectations 1.x)",
        "",
        f"Kết quả GX: **{_pass_fail(quality['success'])}** — {quality['successful_expectations']}/{quality['evaluated_expectations']} expectation đạt. "
        f"Gate tổng (GX + freshness): **{_pass_fail(quality['gate_passed'])}**.",
        "",
        *_expectation_table({"baseline": quality}),
        "",
        "## 4. Freshness SLA",
        "",
        "| Thuộc tính | Giá trị |",
        "| --- | --- |",
        f"| Bài mới nhất | {freshness['latest_published']} |",
        f"| Bài cũ nhất | {freshness['oldest_published']} |",
        f"| Số dòng quá {freshness['freshness_threshold_days']} ngày | {freshness['stale_rows']} / {freshness['total_rows']} ({freshness['stale_ratio']:.1%}) |",
        f"| Tuổi trung vị | {freshness['median_age_days']} ngày |",
        f"| Kết luận | {'Tươi' if freshness['is_fresh'] else 'Quá hạn — cần nạp bài mới'} (ngưỡng: tối đa {freshness['max_stale_ratio']:.0%}) |",
        "",
        "## 5. Artifact đã sinh",
        "",
        *[f"- `{path}`" for path in source_summary.get("artifacts", [])],
        "",
    ]
    write_text(Path(report_path), "\n".join(lines))


def _affected_questions(scenario: dict[str, Any], answers: list[dict[str, Any]]) -> list[str]:
    touched = set(scenario["paper_ids"])
    return [answer["id"] for answer in answers if touched.intersection(answer["ground_truth_doc_ids"])]


def _scenario_detected(scenario_name: str, corrupted_quality: dict[str, Any], baseline_quality: dict[str, Any] | None) -> str:
    detector = SCENARIO_DETECTORS.get(scenario_name)
    if detector is None:
        if baseline_quality:
            return (
                "Không expectation nào bắt được; chỉ lộ ra qua bài mới nhất lùi từ "
                f"{baseline_quality['freshness']['latest_published']} về {corrupted_quality['freshness']['latest_published']}"
            )
        return "Không expectation nào bắt được"
    if detector == "freshness_sla":
        caught = not corrupted_quality["freshness"]["is_fresh"]
        return f"Freshness SLA — {'đã bắt' if caught else 'KHÔNG bắt'}"
    for item in corrupted_quality["expectations"]:
        if _expectation_key(item) == detector:
            return f"`{detector}` — {'đã bắt' if not item['success'] else 'KHÔNG bắt'}"
    return f"`{detector}` — không có trong suite"


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
    baseline_quality: dict[str, Any] | None = None,
    corruption_log: dict[str, Any] | None = None,
    answers_by_state: dict[str, list[dict[str, Any]]] | None = None,
    repair: dict[str, Any] | None = None,
) -> None:
    metrics_by_state = {"baseline": baseline_metrics, "corrupted": corrupted_metrics, "repaired": repaired_metrics}
    quality_by_state = {"corrupted": corrupted_quality, "repaired": repaired_quality}
    if baseline_quality:
        quality_by_state = {"baseline": baseline_quality, **quality_by_state}
    answers_by_state = answers_by_state or {}
    repair = repair or {}

    hit = {state: metrics_by_state[state]["retrieval_hit_rate"] for state in STATES}
    f1 = {state: metrics_by_state[state]["mean_token_f1"] for state in STATES}
    lines = [
        "# Báo cáo đối chiếu 3 trạng thái — Baseline vs Corrupted vs Repaired",
        "",
        f"Sinh tự động bởi `script/run_corruption_flow.py` lúc {now_utc().strftime('%Y-%m-%d %H:%M UTC')}. "
        "Cả ba trạng thái dùng chung `data/eval/test_set.json` và cùng `run_date`.",
        "",
        "## 1. Kết luận nhanh",
        "",
        f"- **Silent failure:** trên dữ liệu bẩn, hit rate {hit['baseline']:.2f} → {hit['corrupted']:.2f} và token F1 "
        f"{f1['baseline']:.2f} → {f1['corrupted']:.2f}, nhưng pipeline không báo lỗi gì và agent vẫn trả lời mọi câu.",
        f"- **Quality gate:** GX {_pass_fail(corrupted_quality['success'])} trên dữ liệu bẩn "
        f"({len(corrupted_quality['failed_expectations'])} expectation fail), freshness {_pass_fail(corrupted_freshness['is_fresh'])}. "
        f"Gate tổng: {_pass_fail(corrupted_quality['gate_passed'])}.",
        f"- **Repair:** hit rate {hit['repaired']:.2f}, token F1 {f1['repaired']:.2f}; gate {_pass_fail(repaired_quality['gate_passed'])}.",
    ]
    if repair:
        lines.append(
            f"- **Idempotent:** bảng sau repair {'trùng khớp' if repair['repaired_matches_baseline'] else 'KHÁC'} bảng baseline "
            f"(sha256 `{repair['repaired_sha256'][:16]}…`)"
            + (f"; {'trùng' if repair['matches_previous_run'] else 'KHÁC'} lần chạy trước." if repair.get("matches_previous_run") is not None else ".")
        )
    lines += [
        "",
        "## 2. Chỉ số RAG",
        "",
        "| Chỉ số | Baseline | Corrupted | Repaired | Δ Corrupted | Δ Repaired |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| Số câu hỏi | {baseline_metrics['samples']} | {corrupted_metrics['samples']} | {repaired_metrics['samples']} | — | — |",
    ]
    for key, label in METRIC_ROWS:
        values = [metrics_by_state[state][key] for state in STATES]
        lines.append(
            f"| {label} | {_format_number(values[0])} | {_format_number(values[1])} | {_format_number(values[2])} "
            f"| {_format_delta(values[1], values[0])} | {_format_delta(values[2], values[0])} |"
        )
    if answers_by_state:
        judge_cells = []
        for state in STATES:
            llm_verdicts, fallback_verdicts = _judge_modes(answers_by_state.get(state, []))
            judge_cells.append(f"{llm_verdicts} / {fallback_verdicts}")
        lines.append(f"| Verdict LLM / heuristic | {' | '.join(judge_cells)} | — | — |")

    lines += ["", "## 3. Quality gate và freshness", "", *_expectation_table(quality_by_state), ""]

    corrupted_answers = answers_by_state.get("corrupted", [])
    if corruption_log:
        lines += [
            "## 4. Sáu kịch bản tiêm lỗi",
            "",
            f"Seed `{corruption_log['seed']}`; {corruption_log['input_rows']} dòng vào, {corruption_log['output_rows']} dòng ra. "
            "Năm kịch bản sau bước bỏ bài nhắm vào các nhóm dòng không trùng nhau; riêng `duplicate_rows` nhân bản dòng bất kỳ, nên có thể chồng lên một kịch bản khác.",
            "",
            "| Kịch bản | Số dòng | Mô tả | Bị phát hiện bởi | Câu hỏi bị ảnh hưởng |",
            "| --- | ---: | --- | --- | --- |",
        ]
        for scenario in corruption_log["scenarios"]:
            affected = _affected_questions(scenario, corrupted_answers) if corrupted_answers else []
            lines.append(
                f"| `{scenario['scenario']}` | {scenario['rows_affected']} | {scenario['description']} "
                f"| {_scenario_detected(scenario['scenario'], corrupted_quality, baseline_quality)} | {', '.join(affected) or '—'} |"
            )
        lines.append("")

    if all(state in answers_by_state for state in STATES):
        scenarios_by_paper: dict[str, list[str]] = defaultdict(list)
        for scenario in (corruption_log or {}).get("scenarios", []):
            for paper_id in scenario["paper_ids"]:
                scenarios_by_paper[paper_id].append(scenario["scenario"])
        answers_by_id = {state: {answer["id"]: answer for answer in answers_by_state[state]} for state in STATES}
        lines += [
            "## 5. Từng câu hỏi",
            "",
            "| ID | Loại | Tài liệu bị tác động bởi | Hit B / C / R | Token F1 B / C / R |",
            "| --- | --- | --- | --- | --- |",
        ]
        for answer in answers_by_state["baseline"]:
            per_state = [answers_by_id[state][answer["id"]] for state in STATES]
            touched_by = sorted({name for doc_id in answer["ground_truth_doc_ids"] for name in scenarios_by_paper.get(doc_id, [])})
            hits = " / ".join("✓" if item["retrieval_hit"] else "✗" for item in per_state)
            f1s = " / ".join(f"{item['token_f1']:.2f}" for item in per_state)
            lines.append(f"| {answer['id']} | {answer['question_type']} | {', '.join(touched_by) or '—'} | {hits} | {f1s} |")
        lines.append("")

    if repair:
        lines += [
            "## 6. Idempotent repair",
            "",
            f"- Nguồn phục hồi: `{repair['source']}`, làm sạch lại bằng đúng `build_clean_dataframe` với `run_date` = {repair['run_date']}.",
            f"- Collection `{repair['collection']}` được xóa và tạo lại mỗi lần chạy, nên không còn vector cũ sót lại.",
            f"- sha256 bảng baseline: `{repair['baseline_sha256']}`",
            f"- sha256 bảng repaired: `{repair['repaired_sha256']}`",
            f"- Repair được kích hoạt {'tự động vì gate fail trên dữ liệu bẩn' if repair['auto_triggered'] else 'thủ công'}.",
        ]
        if repair.get("previous_repaired_sha256"):
            lines.append(f"- sha256 lần chạy trước: `{repair['previous_repaired_sha256']}` → {'trùng khớp' if repair['matches_previous_run'] else 'KHÁC'}.")
        lines.append("")

    write_text(Path(report_path), "\n".join(lines))
