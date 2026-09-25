from __future__ import annotations

import sys
import types

import pytest

from core.utils import read_json, write_json
from evaluation import metrics
from evaluation.metrics import JudgeVerdict, _judge_answer, _token_f1, evaluate_pipeline
from evaluation.testset import build_test_set

VERTEXAI_SHIM = "langchain_community.chat_models.vertexai"


@pytest.mark.parametrize(
    ("reference", "prediction", "expected"),
    [
        ("the cat sat", "the cat sat", 1.0),
        ("The  Cat sat", "the cat   SAT", 1.0),
        ("the cat sat", "dog", 0.0),
        ("", "anything", 0.0),
        ("something", "   ", 0.0),
        ("a b c d", "a b", 2 * 1.0 * 0.5 / 1.5),
    ],
)
def test_token_f1(reference, prediction, expected):
    assert _token_f1(reference, prediction) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("prediction", "score", "correct"),
    [("alpha beta gamma delta", 5, True), ("alpha beta", 3, True), ("zeta", 1, False)],
)
def test_mock_provider_falls_back_to_the_heuristic_judge(settings, prediction, score, correct):
    assert settings.llm_provider == "mock"
    verdict = _judge_answer(settings, "q", "alpha beta gamma delta", prediction)
    assert (verdict.score, verdict.correct) == (score, correct)
    assert verdict.reasoning.startswith("Fallback heuristic judge")


def test_judge_uses_the_llm_verdict_when_available(settings, monkeypatch):
    prompts = []

    class StructuredJudge:
        def invoke(self, prompt):
            prompts.append(prompt)
            return JudgeVerdict(score=4, correct=True, reasoning="close enough")

    class FakeLLM:
        def with_structured_output(self, schema):
            assert schema is JudgeVerdict
            return StructuredJudge()

    monkeypatch.setattr(metrics, "build_llm", lambda settings, temperature: FakeLLM())
    verdict = _judge_answer(settings, "Who?", "Ada", "Ada Lovelace")
    assert verdict == JudgeVerdict(score=4, correct=True, reasoning="close enough")
    assert "Question: Who?" in prompts[0] and "Reference answer: Ada" in prompts[0] and "Model answer: Ada Lovelace" in prompts[0]


def test_ragas_is_skipped_by_default(settings):
    assert "skipped" in metrics._run_ragas(settings, [])


def _answers_for_ragas():
    return [{"question": "q", "answer": "a", "ground_truth": "g", "retrieved_contexts": ["c"]}]


def _install_fake_ragas(monkeypatch, evaluate):
    ragas = types.ModuleType("ragas")
    ragas.evaluate = evaluate
    ragas_metrics = types.ModuleType("ragas.metrics")
    for name in ("answer_relevancy", "context_precision", "context_recall", "faithfulness"):
        setattr(ragas_metrics, name, name)
    monkeypatch.setitem(sys.modules, "ragas", ragas)
    monkeypatch.setitem(sys.modules, "ragas.metrics", ragas_metrics)
    monkeypatch.delitem(sys.modules, VERTEXAI_SHIM, raising=False)
    monkeypatch.setattr(metrics, "MiniLMEmbeddings", lambda model_name: f"embeddings:{model_name}")
    monkeypatch.setenv("RUN_RAGAS", "1")


def test_ragas_pass_runs_when_enabled(settings, monkeypatch):
    calls = {}

    def fake_evaluate(dataset, metrics, llm, embeddings):
        calls.update(rows=len(dataset), columns=sorted(dataset.column_names), metrics=metrics, embeddings=embeddings)
        return {"faithfulness": 0.9}

    _install_fake_ragas(monkeypatch, fake_evaluate)
    assert metrics._run_ragas(settings, _answers_for_ragas()) == {"faithfulness": 0.9}
    assert calls["rows"] == 1
    assert calls["columns"] == ["answer", "contexts", "ground_truth", "question"]
    assert calls["metrics"] == ["answer_relevancy", "context_precision", "context_recall", "faithfulness"]
    assert calls["embeddings"] == f"embeddings:{settings.embedding_model}"
    assert VERTEXAI_SHIM in sys.modules


def test_ragas_failure_is_reported_not_raised(settings, monkeypatch):
    def broken_evaluate(**_kwargs):
        raise RuntimeError("quota")

    _install_fake_ragas(monkeypatch, lambda *args, **kwargs: broken_evaluate())
    result = metrics._run_ragas(settings, _answers_for_ragas())
    assert result["error"].startswith("Ragas evaluation failed") and "quota" in result["error"]


def test_evaluate_pipeline_scores_a_perfect_index(settings, clean_df, fake_index):
    build_test_set(clean_df, settings.paths.eval_testset)
    bundle = evaluate_pipeline(settings, fake_index, settings.paths.eval_testset, settings.paths.baseline_metrics, settings.paths.baseline_answers)

    assert bundle.summary["samples"] == 10
    assert bundle.summary["retrieval_hit_rate"] == 1.0
    assert bundle.summary["mean_token_f1"] == 1.0
    assert bundle.summary["judge_accuracy"] == 1.0
    assert bundle.summary["mean_judge_score"] == 5
    assert bundle.summary["ragas"] == {"skipped": "Set RUN_RAGAS=1 to enable the slower Ragas pass."}
    assert read_json(settings.paths.baseline_metrics) == bundle.summary
    assert read_json(settings.paths.baseline_answers) == bundle.answers
    first = bundle.answers[0]
    assert set(first) == {
        "id", "question_type", "question", "ground_truth", "ground_truth_doc_ids", "answer",
        "retrieved_doc_ids", "retrieved_contexts", "retrieval_hit", "token_f1", "judge",
    }  # fmt: skip
    assert first["retrieved_doc_ids"][0] == first["ground_truth_doc_ids"][0]


def test_evaluate_pipeline_counts_misses(settings, clean_df, make_fake_index, make_search_result):
    build_test_set(clean_df, settings.paths.eval_testset)
    unrelated = make_search_result(clean_df.iloc[0].to_dict())
    blind_index = make_fake_index(rows=[], search_results=[unrelated])
    samples = read_json(settings.paths.eval_testset)
    write_json(settings.paths.eval_testset, [sample for sample in samples if sample["ground_truth_doc_ids"] != [unrelated.paper_id]][:4])

    bundle = evaluate_pipeline(settings, blind_index, settings.paths.eval_testset, settings.paths.corrupted_metrics, settings.paths.corrupted_answers)
    assert bundle.summary["samples"] == 4
    assert bundle.summary["retrieval_hit_rate"] == 0.0
    assert bundle.summary["judge_accuracy"] < 1.0
