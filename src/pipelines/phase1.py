from __future__ import annotations

from collections import Counter
import os
from typing import Any

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import load_or_build_test_set
from ingestion.cleaning import build_clean_dataframe, save_clean_dataframe
from ingestion.crossref import fetch_source_records, ingestion_manifest_path
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from pipelines.common import banner, configure_runtime, describe_metrics, finalize_metrics, redact, rel, step
from retrieval.agent import build_agent, run_agent_question
from retrieval.index import LocalEmbeddingIndex

TOTAL_STEPS = 8
OUT_OF_CORPUS_QUESTION = "What does the indexed corpus say about protein structure prediction with AlphaFold?"


def _message_text(content: Any) -> str:
    if isinstance(content, list):
        parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
        return " ".join(part for part in parts if part).strip()
    return str(content).strip()


def run_agent_demo(settings: Settings, index: LocalEmbeddingIndex, test_set: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask the tool-calling agent a few questions; errors are recorded instead of stopping the pipeline."""
    picks = [next((item for item in test_set if item["question_type"] == kind), None) for kind in ("summary", "authors")]
    questions = [item["question"] for item in picks if item] + [OUT_OF_CORPUS_QUESTION]
    try:
        agent = build_agent(settings, index)
    except Exception as exc:  # missing key or provider package: the demo is optional
        return [{"question": question, "answer": None, "error": redact(f"{type(exc).__name__}: {exc}", settings)} for question in questions]

    results = []
    for question in questions:
        try:
            results.append({"question": question, "answer": _message_text(run_agent_question(agent, question))})
        except Exception as exc:  # rate limit, network, provider error
            results.append({"question": question, "answer": None, "error": redact(f"{type(exc).__name__}: {exc}", settings)})
    return results


def main() -> None:
    """Baseline pipeline: ingest -> clean -> quality gate -> index -> test set -> evaluate -> report."""
    configure_runtime()
    settings = load_settings()
    paths = settings.paths
    run_date = now_utc()
    banner("PHA 1 — BASELINE PIPELINE  (Crossref -> clean -> quality gate -> ChromaDB -> evaluation)")

    step(1, TOTAL_STEPS, "Ingestion & raw lineage")
    records = fetch_source_records(settings)
    ingestion = read_json(ingestion_manifest_path(settings))
    print(
        f"    mode={ingestion['mode']} · {ingestion['valid_records']}/{ingestion['payload_items']} records hợp lệ · "
        f"{ingestion['raw_api_response']} + {ingestion['raw_records_json']}"
    )

    step(2, TOTAL_STEPS, "Cleaning & data modeling")
    clean_df = build_clean_dataframe(records, run_date)
    save_clean_dataframe(clean_df, paths.clean_csv, paths.clean_json)
    cleaning = clean_df.attrs["cleaning_stats"]
    print(
        f"    {cleaning['input_records']} -> {cleaning['output_rows']} dòng sạch (loại {cleaning['dropped_invalid']} không hợp lệ, "
        f"{cleaning['dropped_duplicates']} trùng) · {rel(paths.clean_csv, settings)}"
    )

    step(3, TOTAL_STEPS, "Data quality gate (Great Expectations 1.x) + freshness SLA")
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, paths.freshness_report)
    stats = quality["statistics"]
    print(
        f"    gate: {'PASS' if quality['success'] else 'FAIL'} ({stats['successful_expectations']}/{stats['evaluated_expectations']}) · "
        f"freshness: {freshness['status']} ({freshness['stale_rows']}/{freshness['total_rows']} bài > {freshness['threshold_days']} ngày)"
    )
    if not quality["success"]:
        print(
            f"    Gate chặn dữ liệu: {', '.join(quality['failed_checks'])}. Không index dữ liệu xấu — "
            f"xem {rel(paths.baseline_quality_report, settings)}."
        )
        raise SystemExit(1)
    if not freshness["is_fresh"]:
        print(f"    CẢNH BÁO: {freshness['message']}")

    step(4, TOTAL_STEPS, "Embedding (all-MiniLM-L6-v2) + ChromaDB index")
    index = LocalEmbeddingIndex.build(clean_df, settings, paths.embeddings_json)
    print(f"    collection `{index.collection_name}` · {index.collection.count()} vectors · {rel(paths.chroma_dir, settings)}")

    step(5, TOTAL_STEPS, "Benchmark test set")
    test_set, rebuilt = load_or_build_test_set(clean_df, paths.eval_testset, refresh=settings.refresh_test_set)
    by_type = dict(Counter(item["question_type"] for item in test_set))
    print(f"    {len(test_set)} câu ({'sinh mới' if rebuilt else 'tái sử dụng bộ cố định'}) · {by_type} · {rel(paths.eval_testset, settings)}")

    step(6, TOTAL_STEPS, "Evaluation (hit rate, token F1, LLM judge)")
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)
    metrics = finalize_metrics(bundle, settings, paths.baseline_metrics, "baseline", index.collection_name)
    print(f"    {describe_metrics(metrics)}")

    step(7, TOTAL_STEPS, "QA agent demo (LangChain tool calling)")
    if os.getenv("SKIP_AGENT_DEMO", "").lower() in {"1", "true", "yes"}:
        demo: list[dict[str, Any]] = []
        print("    bỏ qua (SKIP_AGENT_DEMO=1)")
    else:
        demo = run_agent_demo(settings, index, test_set)
        answered = sum(1 for item in demo if not item.get("error"))
        print(f"    {answered}/{len(demo)} câu được agent trả lời · {rel(paths.demo_answers, settings)}")
    write_json(paths.demo_answers, demo)

    step(8, TOTAL_STEPS, "Báo cáo pha 1")
    artifacts = [
        ("Raw API response", paths.raw_api_response),
        ("Raw records", paths.raw_records_json),
        ("Ingestion manifest", ingestion_manifest_path(settings)),
        ("Clean CSV", paths.clean_csv),
        ("Clean JSON", paths.clean_json),
        ("Quality report", paths.baseline_quality_report),
        ("Freshness report", paths.freshness_report),
        ("Embedding manifest", paths.embeddings_json),
        ("Test set", paths.eval_testset),
        ("Baseline metrics", paths.baseline_metrics),
        ("Baseline answers", paths.baseline_answers),
        ("Agent demo", paths.demo_answers),
    ]
    source_summary = {
        "generated_at": now_utc().isoformat(),
        "ingestion": ingestion,
        "cleaning": cleaning,
        "index": {
            "persist_dir": rel(paths.chroma_dir, settings),
            "collection": index.collection_name,
            "documents": index.collection.count(),
            "embedding_model": settings.embedding_model,
            "top_k": settings.top_k,
            "manifest": rel(paths.embeddings_json, settings),
        },
        "test_set": {"path": rel(paths.eval_testset, settings), "questions": len(test_set), "rebuilt": rebuilt, "by_type": by_type},
        "agent_demo": demo,
        "artifacts": [(label, rel(path, settings)) for label, path in artifacts],
    }
    generate_phase1_report(paths.baseline_report, source_summary, metrics, quality, freshness)
    print(f"    {rel(paths.baseline_report, settings)}")
    print("\nHoàn tất pha 1. Tiếp theo: python script/run_corruption_flow.py")
