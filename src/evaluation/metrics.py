from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from statistics import mean
import os
import sys
import time
import types
from typing import Any

from datasets import Dataset
from pydantic import BaseModel, Field

from core.config import Settings, normalized_provider
from core.utils import normalize_whitespace, read_json, write_json
from retrieval.embeddings import MiniLMEmbeddings
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question

JUDGE_ATTEMPTS = 2
JUDGE_RETRY_SECONDS = 2.0
QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "PerDay", "insufficient_quota")


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    correct: bool
    reasoning: str


@dataclass(frozen=True)
class EvaluationBundle:
    summary: dict[str, Any]
    answers: list[dict[str, Any]]


def _token_f1(reference: str, prediction: str) -> float:
    ref_tokens = normalize_whitespace(reference).lower().split()
    pred_tokens = normalize_whitespace(prediction).lower().split()
    if not ref_tokens or not pred_tokens:
        return 0.0
    ref_set = set(ref_tokens)
    pred_set = set(pred_tokens)
    overlap = len(ref_set & pred_set)
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_set)
    recall = overlap / len(ref_set)
    return 2 * precision * recall / (precision + recall)


def _judge_answer(
    settings: Settings,
    question: str,
    reference: str,
    prediction: str,
    cache: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> tuple[JudgeVerdict, str]:
    """Return (verdict, source); source is exact_match, cache, llm or fallback.

    Free LLM tiers allow very few requests per day (gemini-2.5-flash: 20), so exact matches skip the
    LLM, verdicts are cached across runs, and a quota error stops further LLM calls for this run.
    """
    if reference.strip() and normalize_whitespace(reference).lower() == normalize_whitespace(prediction).lower():
        return JudgeVerdict(score=5, correct=True, reasoning="Exact match with the reference answer; LLM call skipped."), "exact_match"

    prompt = f"""
Evaluate the model answer against the reference answer.

Question: {question}
Reference answer: {reference}
Model answer: {prediction}

Return:
- score from 1 to 5
- correct = true only when the answer is materially correct
- short reasoning
""".strip()
    cache_key = hashlib.sha256(json.dumps([normalized_provider(settings), settings.model_name, prompt]).encode("utf-8")).hexdigest()
    if cache is not None and cache_key in cache:
        return JudgeVerdict(**cache[cache_key]), "cache"

    state = state if state is not None else {}
    error = state.get("disabled")
    llm = None
    if error is None:
        try:
            llm = build_llm(settings=settings, temperature=0.0).with_structured_output(JudgeVerdict)
        except Exception as exc:  # missing key or provider without structured output: permanent for this run
            error = state["disabled"] = type(exc).__name__
    for attempt in range(JUDGE_ATTEMPTS if llm is not None else 0):
        try:
            verdict = llm.invoke(prompt)
        except Exception as exc:
            error = type(exc).__name__
            if any(marker in str(exc) for marker in QUOTA_MARKERS):
                error = state["disabled"] = f"{error}: quota exhausted"
                break
        else:
            if verdict is not None:
                if cache is not None:
                    cache[cache_key] = verdict.model_dump()
                return verdict, "llm"
            error = "empty structured output"
        if attempt < JUDGE_ATTEMPTS - 1:
            time.sleep(JUDGE_RETRY_SECONDS * (attempt + 1))

    score = 5 if _token_f1(reference, prediction) >= 0.95 else 3 if _token_f1(reference, prediction) >= 0.5 else 1
    verdict = JudgeVerdict(
        score=score,
        correct=score >= 3,
        reasoning=f"Fallback heuristic judge used because the LLM evaluator was unavailable ({error}).",
    )
    return verdict, "fallback"


def _run_ragas(settings: Settings, answers: list[dict[str, Any]]) -> dict[str, Any]:
    if os.getenv("RUN_RAGAS", "").lower() not in {"1", "true", "yes"}:
        return {"skipped": "Set RUN_RAGAS=1 to enable the slower Ragas pass."}
    try:
        if "langchain_community.chat_models.vertexai" not in sys.modules:
            shim = types.ModuleType("langchain_community.chat_models.vertexai")
            shim.ChatVertexAI = type("ChatVertexAI", (), {})
            sys.modules["langchain_community.chat_models.vertexai"] = shim
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

        dataset = Dataset.from_dict(
            {
                "question": [item["question"] for item in answers],
                "answer": [item["answer"] for item in answers],
                "ground_truth": [item["ground_truth"] for item in answers],
                "contexts": [item["retrieved_contexts"] for item in answers],
            }
        )
        result = evaluate(
            dataset,
            metrics=[answer_relevancy, context_precision, context_recall, faithfulness],
            llm=build_llm(settings=settings, temperature=0.0),
            embeddings=MiniLMEmbeddings(settings.embedding_model),
        )
        return dict(result)
    except Exception as exc:  # pragma: no cover
        return {"error": f"Ragas evaluation failed: {exc}"}


def evaluate_pipeline(
    settings: Settings,
    index: LocalEmbeddingIndex,
    test_set_path,
    metrics_output_path,
    answers_output_path,
) -> EvaluationBundle:
    test_set = read_json(test_set_path)
    answers: list[dict[str, Any]] = []
    cache_path = settings.paths.baseline_metrics.parent / "judge_cache.json"
    cache = read_json(cache_path) if cache_path.exists() else {}
    cached_verdicts = len(cache)
    judge_state: dict[str, Any] = {}

    for item in test_set:
        result = answer_question(item["question"], settings=settings, index=index)
        judge, judge_source = _judge_answer(settings, item["question"], item["ground_truth"], result.answer, cache, judge_state)
        retrieval_hit = any(doc_id in item["ground_truth_doc_ids"] for doc_id in result.retrieved_doc_ids)
        answers.append(
            {
                "id": item["id"],
                "question_type": item["question_type"],
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "ground_truth_doc_ids": item["ground_truth_doc_ids"],
                "answer": result.answer,
                "retrieved_doc_ids": result.retrieved_doc_ids,
                "retrieved_contexts": result.retrieved_contexts,
                "retrieval_hit": retrieval_hit,
                "token_f1": _token_f1(item["ground_truth"], result.answer),
                "judge": judge.model_dump(),
                "judge_source": judge_source,
            }
        )
    if len(cache) != cached_verdicts:
        write_json(cache_path, cache)

    summary = {
        "samples": len(answers),
        "retrieval_hit_rate": mean(1.0 if item["retrieval_hit"] else 0.0 for item in answers),
        "mean_token_f1": mean(item["token_f1"] for item in answers),
        "judge_accuracy": mean(1.0 if item["judge"]["correct"] else 0.0 for item in answers),
        "mean_judge_score": mean(item["judge"]["score"] for item in answers),
    }
    summary["ragas"] = _run_ragas(settings, answers)

    bundle = EvaluationBundle(summary=summary, answers=answers)
    write_json(metrics_output_path, summary)
    write_json(answers_output_path, answers)
    return bundle
