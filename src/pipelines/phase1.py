from __future__ import annotations

from datetime import datetime, timezone

from core.config import load_settings
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import load_or_create_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex


def main() -> None:
    """Xay dung baseline pipeline end-to-end."""
    print("=== BAT DAU RUN PHA 1: BASELINE PIPELINE ===")

    # 1. Load settings
    settings = load_settings()

    # 2. Fetch/load raw source records
    records = fetch_source_records(settings)
    print(f"[1/7] Ingestion: Da nap {len(records)} raw records.")

    # 3. Clean records into Dataframe
    run_date = datetime.now(timezone.utc)
    df_clean = build_clean_dataframe(records, run_date)
    print(f"[2/7] Cleaning: Da lam sach {len(df_clean)} dong.")

    # 4. Save clean artifacts CSV & JSON
    settings.paths.clean_csv.parent.mkdir(parents=True, exist_ok=True)
    df_clean.to_csv(settings.paths.clean_csv, index=False)
    df_clean.to_json(settings.paths.clean_json, orient="records", indent=2, force_ascii=False)
    print(f"[3/7] Artifacts: Da ghi {settings.paths.clean_csv} va {settings.paths.clean_json}")

    # 5. Run Quality Gate (Great Expectations 1.x & Freshness SLA)
    quality_results = run_data_quality_checks(df_clean, settings, "baseline")
    print(f"[4/7] Data Observability: GX 1.x success = {quality_results['success']}, Freshness is_fresh = {quality_results['freshness']['is_fresh']}")

    # 6. Build ChromaDB Vector Store Index
    index = LocalEmbeddingIndex.build(df_clean, settings, embeddings_output_path=settings.paths.embeddings_json)
    print(f"[5/7] Vector Store: Da nap {len(index.documents)} documents vao collection '{index.collection_name}'.")

    # 7. Load or Create Benchmark Test Set
    testset = load_or_create_test_set(df_clean, settings.paths.eval_testset)
    print(f"[6/7] Testset Benchmark: Da tao/nap {len(testset.samples)} cau hoi test.")

    # 8. Evaluate Pipeline
    eval_bundle = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        settings.paths.baseline_metrics,
        settings.paths.baseline_answers,
    )
    print(f"[7/7] Evaluation Metrics: Hit Rate = {eval_bundle.summary['retrieval_hit_rate']:.2f}, Mean Token F1 = {eval_bundle.summary['mean_token_f1']:.2f}")

    # 9. Generate Phase 1 Report
    source_summary = {
        "total_records": len(records),
        "source_api": settings.source_api,
        "query": settings.source_query,
    }
    generate_phase1_report(
        settings.paths.baseline_report,
        source_summary,
        eval_bundle.summary,
        quality_results,
        quality_results["freshness"],
    )
    print(f"=== HOAN THANH PHA 1: Baseline Report da duoc sinh tai {settings.paths.baseline_report} ===")


if __name__ == "__main__":
    main()

