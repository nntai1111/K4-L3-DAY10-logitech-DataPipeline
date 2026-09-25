from __future__ import annotations

import hashlib
import logging
import os

from core.config import load_settings, normalized_provider
from core.utils import now_utc, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import load_or_create_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records_with_mode
from observability.quality import run_data_quality_checks
from observability.reporting import generate_phase1_report
from pipelines.common import choose_run_date, configure_logging, relative, save_table, table_sha256
from retrieval.agent import build_agent, run_agent_question
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)

AGENT_DEMO_QUESTIONS = [
    "Which papers in the corpus discuss freshness SLAs, and what do they propose?",
    "How do the indexed papers suggest detecting silent failures in a RAG pipeline?",
]


def _run_agent_demo(settings, index) -> list[dict]:
    """Ask the tool-using agent a couple of open questions; skipped with RUN_AGENT_DEMO=0 to save quota."""
    if os.getenv("RUN_AGENT_DEMO", "1").lower() in {"0", "false", "no"} or normalized_provider(settings) == "mock":
        return [{"skipped": "Agent demo disabled (RUN_AGENT_DEMO=0 or LLM_PROVIDER=mock)."}]
    try:
        agent = build_agent(settings, index)
    except Exception as error:
        return [{"error": f"Agent could not be built: {error}"}]
    answers = []
    for question in AGENT_DEMO_QUESTIONS:
        try:
            answer = run_agent_question(agent, question)
            answers.append({"question": question, "answer": answer if isinstance(answer, str) else str(answer)})
        except Exception as error:
            answers.append({"question": question, "error": str(error)[:300]})
    return answers


def main() -> None:
    configure_logging()
    settings = load_settings()
    paths = settings.paths
    run_date = choose_run_date(settings)

    records, source_mode = fetch_source_records_with_mode(settings)
    clean_df = build_clean_dataframe(records, run_date)
    save_table(clean_df, paths.clean_csv, paths.clean_json)
    logger.info("Cleaned %d raw records into %d rows (run_date %s)", len(records), len(clean_df), run_date)

    quality = run_data_quality_checks(clean_df, settings, "baseline")
    if not quality["success"]:
        raise SystemExit(f"Quality gate blocked indexing of the baseline: {quality['failed_expectations']}")
    if not quality["freshness"]["is_fresh"]:
        logger.warning("Freshness SLA breached: %s of rows are stale. Refresh the source.", f"{quality['freshness']['stale_ratio']:.0%}")

    index = LocalEmbeddingIndex.build(clean_df, settings, paths.embeddings_json)
    test_set = load_or_create_test_set(clean_df, paths.eval_testset, refresh=settings.refresh_test_set)
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)

    write_json(paths.demo_answers, _run_agent_demo(settings, index))
    write_json(
        paths.run_context,
        {
            "run_date": run_date.isoformat(),
            "generated_at": now_utc().isoformat(timespec="seconds"),
            "source_mode": source_mode,
            "raw_records": len(records),
            "clean_rows": len(clean_df),
            "baseline_sha256": table_sha256(clean_df),
            "test_set_sha256": hashlib.sha256(paths.eval_testset.read_bytes()).hexdigest(),
            "test_set_size": len(test_set.samples),
            "llm_provider": settings.llm_provider,
            "llm_model": settings.model_name,
        },
    )

    artifacts = [
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
    ]
    generate_phase1_report(
        paths.baseline_report,
        source_summary={
            "run_date": run_date.isoformat(),
            "source_api": settings.source_api,
            "source_mode": source_mode,
            "source_query": settings.source_query,
            "source_filter": settings.source_filter,
            "raw_records": len(records),
            "clean_rows": len(clean_df),
            "embedding_model": settings.embedding_model,
            "collection_name": index.collection_name,
            "top_k": settings.top_k,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.model_name,
            "artifacts": [relative(settings, path) for path in artifacts],
        },
        metrics=bundle.summary,
        quality=quality,
        freshness=quality["freshness"],
        answers=bundle.answers,
    )

    summary = bundle.summary
    print("\n=== Phase 1 baseline ===")
    print(f"Rows: {len(clean_df)} | GX: {'PASS' if quality['success'] else 'FAIL'} | fresh: {quality['freshness']['is_fresh']}")
    print(
        f"Hit rate {summary['retrieval_hit_rate']:.3f} | token F1 {summary['mean_token_f1']:.3f} | "
        f"judge accuracy {summary['judge_accuracy']:.3f} | judge score {summary['mean_judge_score']:.2f}"
    )
    print(f"Report: {relative(settings, paths.baseline_report)}")
