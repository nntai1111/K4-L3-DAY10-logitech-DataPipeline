from __future__ import annotations

from datetime import datetime, timezone
import json

import pandas as pd

from core.config import load_settings
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex



def main() -> None:
    """Xay dung corruption -> evaluate -> repair -> compare flow."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=== BAT DAU RUN CORRUPTION & REPAIR PIPELINE ===")

    # 1. Load settings
    settings = load_settings()

    # 2. Load baseline clean dataframe and metrics
    if not settings.paths.clean_json.exists():
        raise FileNotFoundError(f"Clean baseline dataframe not found at {settings.paths.clean_json}. Please run script/run_phase1.py first.")

    df_clean = pd.read_json(settings.paths.clean_json)
    baseline_metrics = json.loads(settings.paths.baseline_metrics.read_text(encoding="utf-8")) if settings.paths.baseline_metrics.exists() else {}

    # --- PHASE 5: DATA CORRUPTION ---
    print("\n--- [1/2] PHA 5: TIEM LOI DU LIEU (SYNTHETIC CORRUPTION) ---")
    df_corrupted = corrupt_clean_dataframe(df_clean, settings.paths.corruption_log)
    print(f"Data Corruption: Da tiem 6 dang loi vao {len(df_corrupted)} dong. Log ghi tai {settings.paths.corruption_log}")

    # Save corrupted artifacts
    settings.paths.corrupted_clean_csv.parent.mkdir(parents=True, exist_ok=True)
    df_corrupted.to_csv(settings.paths.corrupted_clean_csv, index=False)
    df_corrupted.to_json(settings.paths.corrupted_clean_json, orient="records", indent=2, force_ascii=False)

    # Quality check on corrupted data
    corrupted_quality = run_data_quality_checks(df_corrupted, settings, "corrupted")
    print(f"Data Observability (Corrupted): GX 1.x success = {corrupted_quality['success']} (FAIL nhu ky vong)")

    # Index corrupted vector store
    index_corrupted = LocalEmbeddingIndex.build(df_corrupted, settings, embeddings_output_path=settings.paths.corrupted_embeddings_json)

    # Evaluate RAG on corrupted data
    corrupted_eval = evaluate_pipeline(
        settings,
        index_corrupted,
        settings.paths.eval_testset,
        settings.paths.corrupted_metrics,
        settings.paths.corrupted_answers,
    )
    print(f"Corrupted Metrics: Hit Rate = {corrupted_eval.summary['retrieval_hit_rate']:.2f}, Mean Token F1 = {corrupted_eval.summary['mean_token_f1']:.2f}")

    # --- PHASE 6: IDEMPOTENT REPAIR ---
    print("\n--- [2/2] PHA 6: PHUCHOI AN TOAN (IDEMPOTENT REPAIR) ---")
    raw_records = load_raw_records(settings.paths.raw_records_json)
    df_repaired = build_clean_dataframe(raw_records, datetime.now(timezone.utc))

    # Save repaired artifacts
    df_repaired.to_csv(settings.paths.repaired_clean_csv, index=False)
    df_repaired.to_json(settings.paths.repaired_clean_json, orient="records", indent=2, force_ascii=False)
    print(f"Idempotent Repair: Da khoi phuc thanh cong {len(df_repaired)} dong tu raw snapshot {settings.paths.raw_records_json}")

    # Quality check on repaired data
    repaired_quality = run_data_quality_checks(df_repaired, settings, "repaired")
    print(f"Data Observability (Repaired): GX 1.x success = {repaired_quality['success']} (PASS)")

    # Index repaired vector store
    index_repaired = LocalEmbeddingIndex.build(df_repaired, settings, embeddings_output_path=settings.paths.repaired_embeddings_json)

    # Evaluate RAG on repaired data
    repaired_eval = evaluate_pipeline(
        settings,
        index_repaired,
        settings.paths.eval_testset,
        settings.paths.repaired_metrics,
        settings.paths.repaired_answers,
    )
    print(f"Repaired Metrics: Hit Rate = {repaired_eval.summary['retrieval_hit_rate']:.2f}, Mean Token F1 = {repaired_eval.summary['mean_token_f1']:.2f}")

    # Generate comparison report
    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_metrics,
        corrupted_eval.summary,
        repaired_eval.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_quality["freshness"],
        repaired_quality["freshness"],
    )

    print("\n=======================================================")
    print("=== BANG DOI CHIEU HIEU NANG 3 TRANG THAI ===")
    print(f" Baseline (Sach)  : Hit Rate = {baseline_metrics.get('retrieval_hit_rate', 1.0):.2f} | F1 = {baseline_metrics.get('mean_token_f1', 0.0):.2f}")
    print(f" Corrupted (Ban)  : Hit Rate = {corrupted_eval.summary['retrieval_hit_rate']:.2f} | F1 = {corrupted_eval.summary['mean_token_f1']:.2f}")
    print(f" Repaired (Da Sua): Hit Rate = {repaired_eval.summary['retrieval_hit_rate']:.2f} | F1 = {repaired_eval.summary['mean_token_f1']:.2f}")
    print(f"=== Bao cao 3 trang thai da xuat tai: {settings.paths.comparison_report} ===")
    print("=======================================================")



if __name__ == "__main__":
    main()

