from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
from statistics import mean
from typing import Any

from core.utils import write_text

METRIC_KEYS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")
FALLBACK_JUDGE_PREFIX = "Fallback heuristic judge"
CORRUPTION_LABELS = {
    "drop_latest_records": "Drop latest records",
    "blank_summary": "Blank summary",
    "inject_noise": "Inject noise",
    "truncate_title": "Truncate title",
    "stale_date": "Stale date",
    "duplicate_rows": "Duplicate rows",
}


# ---------------------------------------------------------------- helpers


def summarize_answers(answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-question-type breakdown and how each answer was judged (LLM, cache, exact match or fallback)."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for answer in answers:
        grouped[answer["question_type"]].append(answer)
    by_type = {
        question_type: {
            "samples": len(items),
            "retrieval_hit_rate": round(mean(1.0 if item["retrieval_hit"] else 0.0 for item in items), 4),
            "mean_token_f1": round(mean(item["token_f1"] for item in items), 4),
            "judge_accuracy": round(mean(1.0 if item["judge"]["correct"] else 0.0 for item in items), 4),
        }
        for question_type, items in grouped.items()
    }
    sources = Counter(_judge_source(item) for item in answers)
    judge_mode = {
        "llm": sources["llm"],
        "llm_cached": sources["cache"],
        "exact_match": sources["exact_match"],
        "fallback_heuristic": sources["fallback"],
    }
    return {"by_question_type": by_type, "judge_mode": judge_mode}


def _judge_source(answer: dict[str, Any]) -> str:
    if answer.get("judge_source"):
        return answer["judge_source"]
    return "fallback" if str(answer["judge"].get("reasoning", "")).startswith(FALLBACK_JUDGE_PREFIX) else "llm"


def _num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _metric(value: Any, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}" if _is_number(value) else "—"


def _delta(new: Any, old: Any) -> str:
    if not (_is_number(new) and _is_number(old)):
        return "—"
    return f"{new - old:+.3f}"


def _recovery(baseline: Any, corrupted: Any, repaired: Any) -> str:
    if not all(_is_number(value) for value in (baseline, corrupted, repaired)):
        return "—"
    drop = baseline - corrupted
    if abs(drop) < 1e-9:
        return "không suy giảm"
    return f"{(repaired - corrupted) / drop:.0%}"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _code(value: Any, limit: int = 70) -> str:
    text = str(value).replace("`", "'").replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"`{text}`" if text else "`\"\"`"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return lines


def _gate(quality: dict[str, Any] | None) -> str:
    if not quality:
        return "—"
    stats = quality.get("statistics", {})
    counts = f"{stats.get('successful_expectations', '?')}/{stats.get('evaluated_expectations', '?')}"
    return f"✅ PASS ({counts})" if quality.get("success") else f"❌ FAIL ({counts})"


def _fresh_status(freshness: dict[str, Any]) -> str:
    return freshness.get("status") or ("FRESH" if freshness.get("is_fresh") else "STALE")


def _fresh(freshness: dict[str, Any] | None) -> str:
    if not freshness:
        return "—"
    status = _fresh_status(freshness)
    icon = {"FRESH": "✅", "STALE": "⚠️"}.get(status, "❔")
    return f"{icon} {status} ({freshness.get('stale_ratio', 0):.1%} stale)"


def _judge_mode_text(metrics: dict[str, Any]) -> str:
    mode = metrics.get("judge_mode") or {}
    parts = []
    judged_by_llm = mode.get("llm", 0) + mode.get("llm_cached", 0)
    if judged_by_llm:
        cached = f", {mode['llm_cached']} lấy lại từ cache" if mode.get("llm_cached") else ""
        parts.append(f"LLM judge `{metrics.get('llm', 'LLM')}` chấm {judged_by_llm} câu{cached}")
    if mode.get("exact_match"):
        parts.append(f"{mode['exact_match']} câu khớp nguyên văn đáp án (không cần gọi LLM)")
    if mode.get("fallback_heuristic"):
        parts.append(f"{mode['fallback_heuristic']} câu dùng heuristic fallback (LLM lỗi hoặc hết quota)")
    return "; ".join(parts) or "—"


def _title_from_question(question: str) -> str:
    match = re.search(r"'([^']+)'", question)
    return match.group(1) if match else question


def _expectation_rows(quality: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for entry in quality.get("expectations", []):
        evidence = entry.get("observed_value")
        if isinstance(evidence, list):
            evidence = f"{len(evidence)} cột"
        if entry.get("unexpected_count") is not None:
            evidence = f"{entry['unexpected_count']}/{entry.get('element_count')} dòng vi phạm"
        rows.append(
            [
                f"`{entry['check_id']}`",
                entry.get("expectation"),
                entry.get("dimension"),
                "bắt buộc" if entry.get("required") else "mở rộng",
                "✅" if entry.get("success") else "❌",
                _num(evidence),
            ]
        )
    return rows


def _artifact_lines(artifacts: list[tuple[str, str]]) -> list[str]:
    return [f"- {label}: `{path}`" for label, path in artifacts]


# ---------------------------------------------------------------- phase 1


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write the baseline markdown report from the artifacts of the current run."""
    ingestion = source_summary.get("ingestion", {})
    cleaning = source_summary.get("cleaning", {})
    index = source_summary.get("index", {})
    test_set = source_summary.get("test_set", {})
    stats = quality.get("statistics", {})

    lines = [
        "# Báo cáo Pha 1 — Baseline Pipeline",
        "",
        f"> Sinh tự động bởi `script/run_phase1.py` lúc `{source_summary.get('generated_at')}`. "
        "Mọi số liệu bên dưới được đọc từ artifact của chính lần chạy này.",
        "",
        "## Tóm tắt",
        "",
        f"- **Quality gate (Great Expectations 1.x):** {_gate(quality)} — dữ liệu chỉ được index sau khi gate đạt.",
        f"- **Freshness SLA:** {_fresh(freshness)} — {freshness.get('stale_rows')}/{freshness.get('total_rows')} "
        f"bài có `age_days > {freshness.get('threshold_days')}` (ngưỡng cảnh báo {freshness.get('max_stale_ratio', 0):.0%}).",
        f"- **RAG baseline:** hit rate `{_metric(metrics.get('retrieval_hit_rate'))}`, token F1 `{_metric(metrics.get('mean_token_f1'))}`, "
        f"judge accuracy `{_metric(metrics.get('judge_accuracy'))}`, judge score `{_metric(metrics.get('mean_judge_score'), 2)}`/5 "
        f"trên {metrics.get('samples')} câu hỏi.",
        "",
        "## 1. Nguồn dữ liệu & lineage",
        "",
        *_table(
            ["Thuộc tính", "Giá trị"],
            [
                ["Nguồn", f"{ingestion.get('source_api')} — `{ingestion.get('endpoint')}`"],
                ["Chế độ nạp", f"`{ingestion.get('mode')}`" + (f" (lý do fallback: {ingestion['fallback_reason']})" if ingestion.get("fallback_reason") else "")],
                ["Query", f"`{ingestion.get('query')}`"],
                ["Filter (áp dụng khi gọi API live)", f"`{ingestion.get('filter')}`"],
                ["Số item trong payload / hợp lệ", f"{ingestion.get('payload_items')} / {ingestion.get('valid_records')}"],
                ["Raw response (giữ nguyên byte)", f"`{ingestion.get('raw_api_response')}`"],
                ["SHA-256 raw response", f"`{ingestion.get('raw_api_response_sha256')}`"],
                ["Raw records (PaperRecord)", f"`{ingestion.get('raw_records_json')}`"],
            ],
        ),
        "",
        "## 2. Làm sạch & mô hình dữ liệu",
        "",
        *_table(
            ["Chỉ số", "Giá trị"],
            [
                ["Run date (dùng tính `age_days`)", f"`{cleaning.get('run_date')}`"],
                ["Bản ghi đầu vào", cleaning.get("input_records")],
                ["Loại do không hợp lệ", cleaning.get("dropped_invalid")],
                ["Loại do trùng `paper_id`", cleaning.get("dropped_duplicates")],
                ["Số dòng sạch", cleaning.get("output_rows")],
            ],
        ),
        "",
        "Quy tắc làm sạch:",
        "",
        *[f"{position}. {rule}" for position, rule in enumerate(cleaning.get("rules", []), start=1)],
        "",
        "## 3. Data quality gate — Great Expectations 1.x",
        "",
        f"- Engine: {quality.get('engine')}",
        f"- Kết quả: {_gate(quality)} · success_percent = {_num(stats.get('success_percent'), 1)}%",
        f"- Kết quả GX gốc: `{quality.get('gx_validation_result')}`",
        "",
        *_table(["Check", "Expectation", "Chiều chất lượng", "Loại", "Kết quả", "Quan sát"], _expectation_rows(quality)),
        "",
        "## 4. Freshness SLA",
        "",
        *_table(
            ["Thuộc tính", "Giá trị"],
            [
                ["Trạng thái", _fresh(freshness)],
                ["Ngưỡng tuổi", f"{freshness.get('threshold_days')} ngày"],
                ["Tỉ lệ stale tối đa", f"{freshness.get('max_stale_ratio', 0):.0%}"],
                ["Số dòng stale", f"{freshness.get('stale_rows')}/{freshness.get('total_rows')} ({freshness.get('stale_ratio', 0):.1%})"],
                ["Bài mới nhất / cũ nhất", f"{freshness.get('latest_published')} / {freshness.get('oldest_published')}"],
                ["Tuổi nhỏ nhất / trung vị / lớn nhất", f"{freshness.get('newest_age_days')} / {_num(freshness.get('median_age_days'), 1)} / {freshness.get('oldest_age_days')} ngày"],
                ["Thông điệp", freshness.get("message", "—")],
            ],
        ),
        "",
        "## 5. Vector index",
        "",
        *_table(
            ["Thuộc tính", "Giá trị"],
            [
                ["Vector store", f"ChromaDB persistent `{index.get('persist_dir')}`"],
                ["Collection", f"`{index.get('collection')}`"],
                ["Số document", index.get("documents")],
                ["Embedding model", f"`{index.get('embedding_model')}` (normalize, cosine)"],
                ["Retrieval top_k", index.get("top_k")],
                ["Manifest", f"`{index.get('manifest')}`"],
            ],
        ),
        "",
        "## 6. Kết quả đánh giá RAG (baseline)",
        "",
        f"Test set: `{test_set.get('path')}` — {test_set.get('questions')} câu, "
        f"{'vừa sinh mới' if test_set.get('rebuilt') else 'tái sử dụng bộ cố định'}; phân bố: "
        + ", ".join(f"`{kind}` {count}" for kind, count in (test_set.get("by_type") or {}).items())
        + ".",
        "",
        *_table(
            ["Metric", "Giá trị"],
            [
                ["samples", metrics.get("samples")],
                *[[f"`{key}`", _metric(metrics.get(key))] for key in METRIC_KEYS],
                ["Chế độ judge", _judge_mode_text(metrics)],
                ["Ragas", _num((metrics.get("ragas") or {}).get("skipped") or (metrics.get("ragas") or {}).get("error") or "đã chạy")],
            ],
        ),
        "",
        "Theo loại câu hỏi:",
        "",
        *_table(
            ["question_type", "n", "hit rate", "token F1", "judge accuracy"],
            [
                [f"`{kind}`", values["samples"], _metric(values["retrieval_hit_rate"]), _metric(values["mean_token_f1"]), _metric(values["judge_accuracy"])]
                for kind, values in (metrics.get("by_question_type") or {}).items()
            ],
        ),
        "",
    ]
    if _is_number(metrics.get("retrieval_hit_rate")) and metrics["retrieval_hit_rate"] >= 0.999 and metrics.get("mean_token_f1", 0) >= 0.99:
        lines += [
            "**Diễn giải:** baseline đạt mức trần là đúng kỳ vọng của thiết kế. `retrieval/qa.py` trích câu trả lời trực tiếp "
            "từ metadata của tài liệu top-1 (tra cứu chính xác theo tiêu đề trong dấu nháy đơn), còn ground truth của test set "
            "được sinh từ cùng các trường đó của dữ liệu sạch. Vì vậy baseline là mức tham chiếu (upper bound): mọi suy giảm ở "
            "pha corruption đều do dữ liệu, không phải do mô hình.",
            "",
        ]

    demo = source_summary.get("agent_demo") or []
    if demo:
        lines += ["## 7. Demo QA agent (LangChain tool-calling)", ""]
        for item in demo:
            lines.append(f"- **Hỏi:** {item['question']}")
            if item.get("error"):
                lines.append(f"  - **Lỗi:** `{item['error']}`")
            else:
                lines.append(f"  - **Đáp:** {_cell(item.get('answer', '')).strip()}")
        lines.append("")

    lines += ["## 8. Artifacts", "", *_artifact_lines(source_summary.get("artifacts", [])), ""]
    write_text(Path(report_path), "\n".join(lines))


# ---------------------------------------------------------------- corruption / repair


def _detected(signal: str, corrupted_quality: dict[str, Any], corrupted_freshness: dict[str, Any], baseline_freshness: dict[str, Any] | None) -> bool | None:
    if signal == "freshness_sla":
        return not corrupted_freshness.get("is_fresh", True)
    if signal == "freshness.latest_published":
        if not baseline_freshness:
            return None
        return (corrupted_freshness.get("latest_published") or "") < (baseline_freshness.get("latest_published") or "")
    for entry in corrupted_quality.get("expectations", []):
        if entry.get("check_id") == signal:
            return not entry.get("success")
    return None


def _question_rows(answers: dict[str, list[dict[str, Any]]], paper_events: dict[str, list[str]]) -> list[dict[str, Any]]:
    by_state = {state: {item["id"]: item for item in answers.get(state, [])} for state in ("baseline", "corrupted", "repaired")}
    rows = []
    for question_id, base in by_state["baseline"].items():
        corrupted = by_state["corrupted"].get(question_id, {})
        repaired = by_state["repaired"].get(question_id, {})
        paper_id = (base.get("ground_truth_doc_ids") or [""])[0]
        rows.append(
            {
                "id": question_id,
                "type": base.get("question_type"),
                "title": _title_from_question(base.get("question", "")),
                "paper_id": paper_id,
                "corruptions": paper_events.get(paper_id, []),
                "hit": [state.get("retrieval_hit") for state in (base, corrupted, repaired)],
                "f1": [state.get("token_f1") for state in (base, corrupted, repaired)],
                "judge": [(state.get("judge") or {}).get("correct") for state in (base, corrupted, repaired)],
            }
        )
    return rows


def _flag(value: Any) -> str:
    return "—" if value is None else ("✅" if value else "❌")


def _impact_lines(rows: list[dict[str, Any]], events: list[dict[str, Any]], detection: dict[str, list[str]]) -> list[str]:
    lines = []
    for event in events:
        kind = event["type"]
        hit_rows = [row for row in rows if kind in row["corruptions"]]
        detectors = ", ".join(detection.get(kind, [])) or "không có check nào"
        if not hit_rows:
            lines.append(
                f"- **{CORRUPTION_LABELS.get(kind, kind)}** ({event['affected_rows']} dòng): không trúng tài liệu nào của test set "
                f"→ benchmark không thấy lỗi này; chỉ lớp observability phát hiện ({detectors})."
            )
            continue
        lost_hit = [row["id"] for row in hit_rows if row["hit"][0] and not row["hit"][1]]
        f1_drop = [row for row in hit_rows if _is_number(row["f1"][0]) and _is_number(row["f1"][1]) and row["f1"][1] < row["f1"][0] - 1e-9]
        judge_flip = [row["id"] for row in hit_rows if row["judge"][0] and row["judge"][1] is False]
        effects = []
        if lost_hit:
            effects.append(f"mất retrieval hit ở {len(lost_hit)} câu ({', '.join(lost_hit)})")
        if f1_drop:
            average = mean(row["f1"][0] - row["f1"][1] for row in f1_drop)
            effects.append(f"token F1 giảm ở {len(f1_drop)} câu (trung bình −{average:.2f})")
        if judge_flip:
            effects.append(f"judge chuyển sang sai ở {len(judge_flip)} câu ({', '.join(judge_flip)})")
        if not effects:
            effects.append("câu trả lời không đổi vì lỗi không làm sai trường dữ liệu mà câu hỏi sử dụng")
        labels = []
        for row in hit_rows:
            others = [other for other in row["corruptions"] if other != kind]
            labels.append(f"{row['id']} ({row['type']}" + (f"; cùng bị {', '.join(others)}" if others else "") + ")")
        lines.append(f"- **{CORRUPTION_LABELS.get(kind, kind)}** → {', '.join(labels)}: " + "; ".join(effects) + f". Phát hiện bởi: {detectors}.")

    untouched_changed = [
        row["id"]
        for row in rows
        if not row["corruptions"] and (row["hit"][0] != row["hit"][1] or (_is_number(row["f1"][0]) and _is_number(row["f1"][1]) and abs(row["f1"][0] - row["f1"][1]) > 1e-9))
    ]
    if untouched_changed:
        lines.append(
            f"- **Hiệu ứng gián tiếp:** {', '.join(untouched_changed)} thay đổi dù tài liệu ground truth không bị tiêm lỗi "
            "— do tài liệu khác bị hỏng/nhân bản làm thay đổi thứ hạng retrieval."
        )
    wrong_source = [row["id"] for row in rows if row["hit"][1] is False and row["judge"][1] is True]
    if wrong_source:
        lines.append(
            f"- **Silent failure nguy hiểm nhất:** {', '.join(wrong_source)} — tài liệu đúng không còn trong top-k (hit ❌) nhưng "
            "câu trả lời vẫn được judge chấm là đúng, vì hệ thống lấy nội dung gần giống từ một paper khác. Metric chất lượng câu "
            "trả lời không bắt được lỗi này; chỉ retrieval hit và quality gate (`source_papers_present`) cho thấy dữ liệu đã mất."
        )
    return lines


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
    baseline_freshness: dict[str, Any] | None = None,
    corruption_log: dict[str, Any] | None = None,
    answers: dict[str, list[dict[str, Any]]] | None = None,
    repair: dict[str, Any] | None = None,
) -> None:
    """Write the baseline vs corrupted vs repaired comparison report."""
    states = (baseline_metrics, corrupted_metrics, repaired_metrics)
    events = (corruption_log or {}).get("corruptions", [])
    answers = answers or {}
    repair = repair or {}

    paper_events: dict[str, list[str]] = defaultdict(list)
    for event in events:
        for paper_id in dict.fromkeys(event["paper_ids"]):
            paper_events[paper_id].append(event["type"])

    detection: dict[str, list[str]] = {}
    for event in events:
        found = []
        for signal in event.get("detected_by", []):
            if _detected(signal, corrupted_quality, corrupted_freshness, baseline_freshness):
                found.append(f"`{signal}`")
        detection[event["type"]] = found

    rows = _question_rows(answers, paper_events) if answers else []
    hit_b, hit_c = baseline_metrics.get("retrieval_hit_rate"), corrupted_metrics.get("retrieval_hit_rate")
    f1_b, f1_c = baseline_metrics.get("mean_token_f1"), corrupted_metrics.get("mean_token_f1")
    detected_count = sum(1 for event in events if detection.get(event["type"]))

    lines = [
        "# Báo cáo Corruption & Repair — Đối chiếu 3 trạng thái",
        "",
        f"> Sinh tự động bởi `script/run_corruption_flow.py` lúc `{repair.get('generated_at', '—')}`. "
        f"Cả 3 trạng thái được đánh giá trên **cùng một test set** ({baseline_metrics.get('samples')} câu) "
        "và cùng cấu hình retrieval/LLM.",
        "",
        "## Tóm tắt",
        "",
        f"- **Silent failure:** pipeline index và trả lời trên dữ liệu hỏng mà **không phát sinh lỗi nào**, nhưng hit rate "
        f"`{_metric(hit_b)} → {_metric(hit_c)}` và token F1 `{_metric(f1_b)} → {_metric(f1_c)}`.",
        f"- **Observability phát hiện:** gate GX {_gate(corrupted_quality)}, failed checks: "
        + (", ".join(f"`{check}`" for check in corrupted_quality.get("failed_checks", [])) or "không có")
        + f"; freshness {_fresh(corrupted_freshness)}. Phát hiện {detected_count}/{len(events)} kịch bản tiêm lỗi.",
        f"- **Repair:** dựng lại từ `{repair.get('source', 'raw snapshot')}` → gate {_gate(repaired_quality)}, freshness "
        f"{_fresh(repaired_freshness)}, hit rate `{_metric(repaired_metrics.get('retrieval_hit_rate'))}`, token F1 "
        f"`{_metric(repaired_metrics.get('mean_token_f1'))}`. Idempotent: {'✅' if repair.get('idempotent') else '❌'}; "
        f"khớp baseline: {'✅' if repair.get('matches_baseline') else '❌'}.",
        "",
        "## 1. Bảng đối chiếu 3 trạng thái",
        "",
        *_table(
            ["Metric / signal", "Baseline", "Corrupted", "Repaired", "Δ Corrupted − Baseline", "Δ Repaired − Baseline", "Mức phục hồi"],
            [
                *[
                    [f"`{key}`", *(_metric(state.get(key)) for state in states), _delta(corrupted_metrics.get(key), baseline_metrics.get(key)),
                     _delta(repaired_metrics.get(key), baseline_metrics.get(key)),
                     _recovery(baseline_metrics.get(key), corrupted_metrics.get(key), repaired_metrics.get(key))]
                    for key in METRIC_KEYS
                ],
                ["Quality gate (GX 1.x)", _gate(baseline_quality), _gate(corrupted_quality), _gate(repaired_quality), "", "", ""],
                ["Freshness SLA", _fresh(baseline_freshness), _fresh(corrupted_freshness), _fresh(repaired_freshness), "", "", ""],
                [
                    "Số dòng / paper_id duy nhất",
                    *(f"{quality.get('row_count')} / {quality.get('unique_paper_ids')}" if quality else "—" for quality in (baseline_quality, corrupted_quality, repaired_quality)),
                    "", "", "",
                ],
                [
                    "Bài mới nhất (`latest_published`)",
                    *((freshness or {}).get("latest_published", "—") for freshness in (baseline_freshness, corrupted_freshness, repaired_freshness)),
                    "", "", "",
                ],
                ["Chế độ judge", *(_judge_mode_text(state) for state in states), "", "", ""],
            ],
        ),
        "",
        "Mức phục hồi = (Repaired − Corrupted) / (Baseline − Corrupted); 100% nghĩa là trở về đúng baseline.",
        "",
        "## 2. Quality gate theo từng expectation",
        "",
    ]

    base_by_id = {entry["check_id"]: entry for entry in (baseline_quality or {}).get("expectations", [])}
    rep_by_id = {entry["check_id"]: entry for entry in repaired_quality.get("expectations", [])}
    gate_rows = []
    for entry in corrupted_quality.get("expectations", []):
        evidence = ""
        if not entry.get("success"):
            if entry.get("missing_count"):
                evidence = f"thiếu {entry['missing_count']} paper, vd {_code(entry.get('missing_examples', [''])[0])}"
            elif entry.get("unexpected_count") is not None:
                example = (entry.get("unexpected_examples") or [""])[0]
                evidence = f"{entry['unexpected_count']} dòng vi phạm, vd {_code(example)}"
            else:
                evidence = _num(entry.get("observed_value"))
        gate_rows.append(
            [
                f"`{entry['check_id']}`",
                entry.get("dimension"),
                _flag((base_by_id.get(entry["check_id"]) or {}).get("success") if base_by_id else None),
                _flag(entry.get("success")),
                _flag((rep_by_id.get(entry["check_id"]) or {}).get("success")),
                evidence,
            ]
        )
    lines += [*_table(["Check", "Chiều", "Baseline", "Corrupted", "Repaired", "Bằng chứng (corrupted)"], gate_rows), ""]

    lines += [
        "## 3. Freshness SLA",
        "",
        *_table(
            ["Thuộc tính", "Baseline", "Corrupted", "Repaired"],
            [
                ["Trạng thái", _fresh(baseline_freshness), _fresh(corrupted_freshness), _fresh(repaired_freshness)],
                *[
                    [label, *(_num((freshness or {}).get(key)) for freshness in (baseline_freshness, corrupted_freshness, repaired_freshness))]
                    for label, key in (
                        ("Dòng stale", "stale_rows"),
                        ("Tổng dòng", "total_rows"),
                        ("Tỉ lệ stale", "stale_ratio"),
                        ("Bài mới nhất", "latest_published"),
                        ("Bài cũ nhất", "oldest_published"),
                        ("Tuổi nhỏ nhất (ngày)", "newest_age_days"),
                    )
                ],
            ],
        ),
        "",
        "## 4. Sáu kịch bản tiêm lỗi (`data/results/corruption_log.json`)",
        "",
        f"Seed `{(corruption_log or {}).get('seed')}` — {(corruption_log or {}).get('input_rows')} dòng sạch → "
        f"{(corruption_log or {}).get('output_rows')} dòng hỏng ({(corruption_log or {}).get('unique_papers')} paper duy nhất).",
        "",
        *_table(
            ["#", "Kịch bản", "Mô tả", "Tham số", "Dòng", "Tín hiệu kỳ vọng", "Đã phát hiện?"],
            [
                [
                    event["step"],
                    CORRUPTION_LABELS.get(event["type"], event["type"]),
                    event["description"],
                    ", ".join(f"{key}={value}" for key, value in event["parameters"].items()),
                    event["affected_rows"],
                    ", ".join(f"`{signal}`" for signal in event.get("detected_by", [])),
                    ("✅ " + ", ".join(detection[event["type"]])) if detection.get(event["type"]) else "❌",
                ]
                for event in events
            ],
        ),
        "",
        "Ví dụ trước/sau:",
        "",
    ]
    for event in events:
        example = (event.get("examples") or [{}])[0]
        if "before" in example:
            lines.append(f"- {CORRUPTION_LABELS.get(event['type'], event['type'])}: {_code(example['before'])} → {_code(example['after'])}")
        elif example:
            lines.append(f"- {CORRUPTION_LABELS.get(event['type'], event['type'])}: " + ", ".join(f"{key}={_code(value)}" for key, value in example.items()))
    lines.append("")

    if rows:
        lines += [
            "## 5. Tác động lên từng câu hỏi",
            "",
            *_table(
                ["id", "Loại", "Paper", "Lỗi trên paper", "Hit B/C/R", "Token F1 B/C/R", "Judge B/C/R"],
                [
                    [
                        row["id"],
                        row["type"],
                        _code(row["title"], 45),
                        ", ".join(row["corruptions"]) or "—",
                        " / ".join(_flag(value) for value in row["hit"]),
                        " / ".join(_num(value, 2) for value in row["f1"]),
                        " / ".join(_flag(value) for value in row["judge"]),
                    ]
                    for row in rows
                ],
            ),
            "",
            "## 6. Phân tích nguyên nhân → hệ quả",
            "",
            *_impact_lines(rows, events, detection),
            "",
            "Kết luận: benchmark chỉ bao phủ các paper nằm trong test set, nên có lỗi dữ liệu không làm đổi metric nào. "
            "Quality gate và freshness SLA kiểm tra **toàn bộ** dataset, nên phát hiện được cả những lỗi mà metric RAG không thấy.",
            "",
        ]

    fingerprints = repair.get("fingerprints", {})
    trigger = repair.get("trigger", {})
    lines += [
        "## 7. Repair & tính idempotent",
        "",
        f"- **Kích hoạt:** tự động vì gate thất bại ({', '.join(f'`{check}`' for check in trigger.get('failed_checks', [])) or '—'}) "
        f"và freshness `{trigger.get('freshness_status', '—')}`.",
        f"- **Nguồn phục hồi:** `{repair.get('source', '—')}`; kiểm tra lineage với `{repair.get('lineage_reference', '—')}`: "
        f"{'✅ khớp' if repair.get('lineage_verified') else '❌ lệch'}.",
        "- **Cách làm:** parse lại raw → áp đúng quy tắc cleaning của baseline → validate lại bằng gate → chỉ index khi gate đạt. "
        "Không vá tay dữ liệu hỏng, nên chạy lại bao nhiêu lần cũng ra cùng một dataset.",
        "",
        *_table(
            ["Dataset", "Fingerprint (SHA-256 nội dung)", "Khớp baseline?"],
            [
                [label, f"`{fingerprints.get(key, '—')[:16]}…`", _flag(fingerprints.get(key) == fingerprints.get("baseline_clean")) if key != "baseline_clean" else "—"]
                for label, key in (
                    ("Baseline clean (pha 1)", "baseline_clean"),
                    ("Corrupted", "corrupted"),
                    ("Repair lần 1", "repair_run_1"),
                    ("Repair lần 2", "repair_run_2"),
                )
                if key in fingerprints
            ],
        ),
        "",
        "## 8. Artifacts",
        "",
        *_artifact_lines(repair.get("artifacts", [])),
        "",
    ]
    write_text(Path(report_path), "\n".join(lines))


def format_comparison_table(
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
    qualities: tuple[dict[str, Any] | None, ...],
    freshnesses: tuple[dict[str, Any] | None, ...],
) -> str:
    """Plain-text 3-state table for the console demo."""

    def gate(quality: dict[str, Any] | None) -> str:
        return "—" if not quality else ("PASS" if quality.get("success") else "FAIL")

    def fresh(freshness: dict[str, Any] | None) -> str:
        return "—" if not freshness else f"{_fresh_status(freshness)} {freshness.get('stale_ratio', 0):.0%}"

    rows = [("Metric", "Baseline", "Corrupted", "Repaired")]
    rows += [(key, *(_metric(state.get(key)) for state in (baseline, corrupted, repaired))) for key in METRIC_KEYS]
    rows.append(("quality_gate", *(gate(quality) for quality in qualities)))
    rows.append(("freshness", *(fresh(freshness) for freshness in freshnesses)))
    widths = [max(len(str(row[column])) for row in rows) for column in range(4)]
    rendered = [
        "  ".join(str(value).ljust(widths[column]) if column == 0 else str(value).rjust(widths[column]) for column, value in enumerate(row))
        for row in rows
    ]
    rendered.insert(1, "-" * len(rendered[0]))
    return "\n".join(rendered)
