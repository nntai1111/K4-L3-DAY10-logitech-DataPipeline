from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe, dataset_fingerprint, load_clean_dataframe, save_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records, parse_crossref_payload
from observability.quality import build_freshness_report, freshness_report_path, quality_report_path, run_data_quality_checks
from observability.reporting import format_comparison_table, generate_corruption_report
from pipelines.common import banner, configure_runtime, describe_metrics, finalize_metrics, rel, step
from retrieval.index import LocalEmbeddingIndex

TOTAL_STEPS = 6


def _read_optional(path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def _gate_line(quality: dict[str, Any], freshness: dict[str, Any]) -> str:
    stats = quality["statistics"]
    failed = ", ".join(quality["failed_checks"]) or "—"
    return (
        f"gate: {'PASS' if quality['success'] else 'FAIL'} ({stats['successful_expectations']}/{stats['evaluated_expectations']}) "
        f"· failed: {failed} · freshness: {freshness['status']} ({freshness['stale_ratio']:.1%} stale)"
    )


def repair_from_raw(settings: Settings, run_date: datetime) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Rebuild the dataset from the preserved raw snapshot with the baseline cleaning rules.

    The transformation runs twice to prove it is idempotent (same fingerprint every time).
    """
    paths = settings.paths
    records = load_raw_records(paths.raw_records_json)
    lineage_verified = None
    if paths.raw_api_response.exists():
        lineage_verified = parse_crossref_payload(read_json(paths.raw_api_response)) == records

    first = build_clean_dataframe(records, run_date)
    second = build_clean_dataframe(load_raw_records(paths.raw_records_json), run_date)
    details = {
        "source": rel(paths.raw_records_json, settings),
        "lineage_reference": rel(paths.raw_api_response, settings),
        "lineage_verified": lineage_verified,
        "rows": len(first),
        "fingerprints": {"repair_run_1": dataset_fingerprint(first), "repair_run_2": dataset_fingerprint(second)},
    }
    return first, details


def main() -> None:
    """Corruption -> detection -> silent-failure measurement -> auto repair -> 3-state comparison."""
    configure_runtime()
    settings = load_settings()
    paths = settings.paths
    run_date = now_utc()

    required = [paths.clean_json, paths.baseline_metrics, paths.eval_testset]
    missing = [rel(path, settings) for path in required if not path.exists()]
    if missing:
        print(f"Thiếu artifact của pha 1: {', '.join(missing)}. Hãy chạy `python script/run_phase1.py` trước.")
        raise SystemExit(1)

    banner("PHA 2 — CORRUPTION -> OBSERVABILITY ALERT -> IDEMPOTENT REPAIR")
    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_quality = _read_optional(paths.baseline_quality_report)
    baseline_freshness = _read_optional(paths.freshness_report)
    clean_df = load_clean_dataframe(paths.clean_json)

    step(1, TOTAL_STEPS, "Tiêm 6 kịch bản lỗi dữ liệu")
    corrupted_df = corrupt_clean_dataframe(clean_df, paths.corruption_log)
    save_clean_dataframe(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)
    corruption_log = read_json(paths.corruption_log)
    for event in corruption_log["corruptions"]:
        print(f"    {event['step']}. {event['type']:<20} {event['affected_rows']} dòng")
    print(f"    {len(clean_df)} -> {len(corrupted_df)} dòng · {rel(paths.corruption_log, settings)}")

    step(2, TOTAL_STEPS, "Observability trên dữ liệu hỏng (GX 1.x + freshness)")
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(corrupted_df, settings, freshness_report_path(settings, "corrupted"))
    print(f"    {_gate_line(corrupted_quality, corrupted_freshness)}")

    step(3, TOTAL_STEPS, "Silent failure: index + đánh giá dữ liệu hỏng như thể không có gate")
    corrupted_index = LocalEmbeddingIndex.build(corrupted_df, settings, paths.corrupted_embeddings_json)
    corrupted_bundle = evaluate_pipeline(settings, corrupted_index, paths.eval_testset, paths.corrupted_metrics, paths.corrupted_answers)
    corrupted_metrics = finalize_metrics(corrupted_bundle, settings, paths.corrupted_metrics, "corrupted", corrupted_index.collection_name)
    print(f"    pipeline chạy không lỗi, nhưng: {describe_metrics(corrupted_metrics)}")

    step(4, TOTAL_STEPS, "Auto-repair từ raw snapshot")
    gate_failed = not corrupted_quality["success"] or not corrupted_freshness["is_fresh"]
    print(
        "    gate thất bại -> tự động kích hoạt repair"
        if gate_failed
        else "    gate KHÔNG phát hiện lỗi -> vẫn repair để đối chiếu (cần xem lại độ phủ của gate)"
    )
    repaired_df, repair = repair_from_raw(settings, run_date)
    save_clean_dataframe(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(repaired_df, settings, freshness_report_path(settings, "repaired"))
    print(f"    {_gate_line(repaired_quality, repaired_freshness)}")
    if not repaired_quality["success"]:
        print("    Dữ liệu sau repair vẫn không đạt gate -> dừng, không publish index.")
        raise SystemExit(1)

    fingerprints = {
        "baseline_clean": dataset_fingerprint(clean_df),
        "corrupted": dataset_fingerprint(corrupted_df),
        **repair["fingerprints"],
    }
    repair.update(
        {
            "generated_at": now_utc().isoformat(),
            "trigger": {
                "gate_failed": gate_failed,
                "failed_checks": corrupted_quality["failed_checks"],
                "freshness_status": corrupted_freshness["status"],
            },
            "fingerprints": fingerprints,
            "idempotent": fingerprints["repair_run_1"] == fingerprints["repair_run_2"],
            "matches_baseline": fingerprints["repair_run_1"] == fingerprints["baseline_clean"],
        }
    )
    print(f"    idempotent: {repair['idempotent']} · khớp baseline: {repair['matches_baseline']} · lineage raw: {repair['lineage_verified']}")

    step(5, TOTAL_STEPS, "Index + đánh giá dữ liệu đã phục hồi")
    repaired_index = LocalEmbeddingIndex.build(repaired_df, settings, paths.repaired_embeddings_json)
    repaired_bundle = evaluate_pipeline(settings, repaired_index, paths.eval_testset, paths.repaired_metrics, paths.repaired_answers)
    repaired_metrics = finalize_metrics(repaired_bundle, settings, paths.repaired_metrics, "repaired", repaired_index.collection_name)
    print(f"    {describe_metrics(repaired_metrics)}")

    step(6, TOTAL_STEPS, "Báo cáo đối chiếu 3 trạng thái")
    repair_log_path = paths.corruption_log.parent / "repair_log.json"
    artifacts = [
        ("Corruption log", paths.corruption_log),
        ("Corrupted dataset", paths.corrupted_clean_csv),
        ("Corrupted quality report", paths.corrupted_quality_report),
        ("Corrupted freshness", freshness_report_path(settings, "corrupted")),
        ("Corrupted metrics", paths.corrupted_metrics),
        ("Corrupted answers", paths.corrupted_answers),
        ("Repaired dataset", paths.repaired_clean_csv),
        ("Repaired quality report", quality_report_path(settings, "repaired")),
        ("Repaired freshness", freshness_report_path(settings, "repaired")),
        ("Repaired metrics", paths.repaired_metrics),
        ("Repaired answers", paths.repaired_answers),
        ("Repair log", repair_log_path),
    ]
    repair["artifacts"] = [(label, rel(path, settings)) for label, path in artifacts]
    write_json(repair_log_path, repair)

    answers = {
        "baseline": read_json(paths.baseline_answers) if paths.baseline_answers.exists() else [],
        "corrupted": corrupted_bundle.answers,
        "repaired": repaired_bundle.answers,
    }
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
        baseline_quality=baseline_quality,
        baseline_freshness=baseline_freshness,
        corruption_log=corruption_log,
        answers=answers,
        repair=repair,
    )
    print(f"    {rel(paths.comparison_report, settings)}\n")
    print(
        format_comparison_table(
            baseline_metrics,
            corrupted_metrics,
            repaired_metrics,
            (baseline_quality, corrupted_quality, repaired_quality),
            (baseline_freshness, corrupted_freshness, repaired_freshness),
        )
    )
    print("\nHoàn tất pha 2.")
