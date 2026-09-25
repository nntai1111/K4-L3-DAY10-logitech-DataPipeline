from __future__ import annotations

from datetime import date
import logging

from core.config import load_settings
from core.utils import now_utc, read_json, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_corruption_report
from pipelines.common import configure_logging, load_run_context, read_table, relative, save_table, table_sha256
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)


def _repair_from_raw(settings, run_date: date):
    """Rebuild the clean table from the untouched raw records. Same input and same run_date give the
    same table on every run, which is what makes the repair idempotent."""
    records = load_raw_records(settings.paths.raw_records_json)
    return build_clean_dataframe(records, run_date)


def main() -> None:
    configure_logging()
    settings = load_settings()
    paths = settings.paths
    context = load_run_context(settings)
    run_date = date.fromisoformat(context["run_date"])

    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_answers = read_json(paths.baseline_answers)
    baseline_quality = read_json(paths.baseline_quality_report)
    clean_df = read_table(paths.clean_json)

    # 1. Corrupt a copy of the baseline and measure what the RAG does with it.
    corrupted_df = corrupt_clean_dataframe(clean_df, paths.corruption_log)
    save_table(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    logger.info(
        "Corrupted batch: GX %s, fresh %s, failed %s",
        "PASS" if corrupted_quality["success"] else "FAIL",
        corrupted_quality["freshness"]["is_fresh"],
        corrupted_quality["failed_expectations"],
    )
    # In production a failed gate stops the batch here. The experiment indexes it anyway
    # (observe mode) to measure how much damage would have reached the agent.
    corrupted_index = LocalEmbeddingIndex.build(corrupted_df, settings, paths.corrupted_embeddings_json)
    corrupted_bundle = evaluate_pipeline(settings, corrupted_index, paths.eval_testset, paths.corrupted_metrics, paths.corrupted_answers)

    # 2. Repair. It triggers itself when the gate fails; the lab runs it either way for the comparison.
    auto_triggered = not corrupted_quality["gate_passed"]
    logger.info("Repair %s", "auto-triggered by the failed gate" if auto_triggered else "run manually: the gate passed")
    repaired_df = _repair_from_raw(settings, run_date)
    save_table(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    if not repaired_quality["success"]:
        raise SystemExit(f"Repaired data still fails the gate: {repaired_quality['failed_expectations']}")
    repaired_index = LocalEmbeddingIndex.build(repaired_df, settings, paths.repaired_embeddings_json)
    repaired_bundle = evaluate_pipeline(settings, repaired_index, paths.eval_testset, paths.repaired_metrics, paths.repaired_answers)

    # 3. Prove idempotency: repaired == baseline, and == the previous repair run.
    repair_log_path = paths.project_dir / "data" / "results" / "repair_idempotency.json"
    previous = read_json(repair_log_path) if repair_log_path.exists() else {}
    repaired_sha256 = table_sha256(repaired_df)
    previous_sha256 = previous.get("repaired_sha256")
    repair = {
        "generated_at": now_utc().isoformat(timespec="seconds"),
        "source": relative(settings, paths.raw_records_json),
        "run_date": run_date.isoformat(),
        "collection": repaired_index.collection_name,
        "auto_triggered": auto_triggered,
        "baseline_sha256": context["baseline_sha256"],
        "repaired_sha256": repaired_sha256,
        "repaired_matches_baseline": repaired_sha256 == context["baseline_sha256"],
        "previous_repaired_sha256": previous_sha256,
        "matches_previous_run": None if previous_sha256 is None else previous_sha256 == repaired_sha256,
    }
    write_json(repair_log_path, repair)

    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics=baseline_metrics,
        corrupted_metrics=corrupted_bundle.summary,
        repaired_metrics=repaired_bundle.summary,
        corrupted_quality=corrupted_quality,
        repaired_quality=repaired_quality,
        corrupted_freshness=corrupted_quality["freshness"],
        repaired_freshness=repaired_quality["freshness"],
        baseline_quality=baseline_quality,
        corruption_log=read_json(paths.corruption_log),
        answers_by_state={"baseline": baseline_answers, "corrupted": corrupted_bundle.answers, "repaired": repaired_bundle.answers},
        repair=repair,
    )

    rows = [
        ("Hit rate", "retrieval_hit_rate"),
        ("Token F1", "mean_token_f1"),
        ("Judge accuracy", "judge_accuracy"),
        ("Judge score", "mean_judge_score"),
    ]
    states = [baseline_metrics, corrupted_bundle.summary, repaired_bundle.summary]
    print("\n=== Baseline vs Corrupted vs Repaired ===")
    print(f"{'Metric':<16}{'Baseline':>10}{'Corrupted':>11}{'Repaired':>10}")
    for label, key in rows:
        print(f"{label:<16}" + "".join(f"{state[key]:>10.3f} " for state in states))
    gate_states = [baseline_quality, corrupted_quality, repaired_quality]
    print(f"{'Gate':<16}" + "".join(f"{('PASS' if gate['gate_passed'] else 'FAIL'):>10} " for gate in gate_states))
    print(f"Repaired == baseline: {repair['repaired_matches_baseline']} | same as previous run: {repair['matches_previous_run']}")
    print(f"Report: {relative(settings, paths.comparison_report)}")
