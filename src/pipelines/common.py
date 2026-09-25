from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from transformers.utils import logging as transformers_logging

from core.config import Settings, normalized_provider
from core.utils import now_utc, project_relative, write_json
from evaluation.metrics import EvaluationBundle
from observability.reporting import summarize_answers


def configure_runtime() -> None:
    """UTF-8 console output (Windows pipes default to cp1252) and quieter third-party libraries."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except (OSError, ValueError):
                pass
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    # The Xet transfer backend can stall at 0 bytes on some Windows networks; plain HTTP is reliable.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    transformers_logging.disable_progress_bar()  # the per-load "Loading weights" bar clutters the demo output


def rel(path: Path, settings: Settings) -> str:
    return project_relative(path, settings.paths.project_dir)


def redact(text: str, settings: Settings) -> str:
    """Remove API keys from error messages before they are written to artifacts."""
    for secret in (
        settings.google_api_key,
        settings.openai_api_key,
        settings.anthropic_api_key,
        settings.openrouter_api_key,
        settings.custom_llm_api_key,
    ):
        if secret:
            text = text.replace(secret, "***")
    return text


def banner(title: str) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)


def step(index: int, total: int, title: str) -> None:
    print(f"\n[{index}/{total}] {title}")


def finalize_metrics(
    bundle: EvaluationBundle,
    settings: Settings,
    metrics_path: Path,
    state: str,
    collection_name: str,
) -> dict[str, Any]:
    """Enrich the summary written by evaluate_pipeline with state, LLM and per-question-type breakdown."""
    metrics = {
        **bundle.summary,
        "state": state,
        "collection": collection_name,
        "llm": f"{normalized_provider(settings)}/{settings.model_name}",
        "evaluated_at": now_utc().isoformat(),
        **summarize_answers(bundle.answers),
    }
    write_json(metrics_path, metrics)
    return metrics


def describe_metrics(metrics: dict[str, Any]) -> str:
    judge = metrics.get("judge_mode", {})
    return (
        f"hit rate {metrics['retrieval_hit_rate']:.3f} · token F1 {metrics['mean_token_f1']:.3f} · "
        f"judge acc {metrics['judge_accuracy']:.3f} · judge score {metrics['mean_judge_score']:.2f}/5 "
        f"(judge: LLM {judge.get('llm', 0)}, cache {judge.get('llm_cached', 0)}, "
        f"exact match {judge.get('exact_match', 0)}, fallback {judge.get('fallback_heuristic', 0)})"
    )
