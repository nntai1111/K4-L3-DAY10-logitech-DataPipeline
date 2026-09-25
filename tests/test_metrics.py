from __future__ import annotations

import pytest

from evaluation import metrics
from evaluation.metrics import JudgeVerdict, _judge_answer


class FakeJudge:
    """Stands in for `build_llm(...).with_structured_output(JudgeVerdict)` with scripted outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_llm(monkeypatch):
    def install(*outcomes):
        judge = FakeJudge(outcomes)
        monkeypatch.setattr(metrics, "build_llm", lambda settings, temperature: judge)
        monkeypatch.setattr(metrics.time, "sleep", lambda seconds: None)
        return judge

    return install


def test_exact_match_skips_the_llm(settings, fake_llm):
    judge = fake_llm()
    verdict, source = _judge_answer(settings, "q", "Ann Le, Binh Tran", "  ann le,  BINH tran ")
    assert (source, verdict.score, verdict.correct, judge.calls) == ("exact_match", 5, True, 0)


def test_llm_verdicts_are_cached_across_calls(settings, fake_llm):
    judge = fake_llm(JudgeVerdict(score=4, correct=True, reasoning="close enough"))
    cache: dict = {}
    first = _judge_answer(settings, "q", "reference answer", "a paraphrase", cache)
    second = _judge_answer(settings, "q", "reference answer", "a paraphrase", cache)
    assert (first[1], second[1]) == ("llm", "cache")
    assert first[0] == second[0]
    assert judge.calls == 1 and len(cache) == 1


def test_transient_failure_is_retried(settings, fake_llm):
    judge = fake_llm(RuntimeError("503 UNAVAILABLE"), JudgeVerdict(score=2, correct=False, reasoning="wrong paper"))
    verdict, source = _judge_answer(settings, "q", "reference", "other answer")
    assert (source, verdict.score, judge.calls) == ("llm", 2, 2)


def test_daily_quota_error_stops_further_llm_calls(settings, fake_llm):
    judge = fake_llm(RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    state: dict = {}
    verdict, source = _judge_answer(settings, "q", "alpha beta", "alpha beta gamma", state=state)
    assert source == "fallback" and "quota exhausted" in verdict.reasoning
    assert (verdict.score, verdict.correct) == (3, True)  # token F1 0.8 -> heuristic score 3
    again, source = _judge_answer(settings, "q2", "alpha", "beta", state=state)
    assert source == "fallback" and (again.score, again.correct) == (1, False)
    assert judge.calls == 1


def test_empty_structured_output_falls_back_after_retries(settings, fake_llm):
    judge = fake_llm(None, None)
    verdict, source = _judge_answer(settings, "q", "alpha beta", "alpha beta gamma")
    assert source == "fallback" and "empty structured output" in verdict.reasoning
    assert judge.calls == metrics.JUDGE_ATTEMPTS


def test_provider_without_structured_output_disables_the_judge(settings):
    state: dict = {}
    verdict, source = _judge_answer(settings, "q", "alpha", "beta", state=state)  # LLM_PROVIDER=mock
    assert source == "fallback"
    assert state["disabled"] == "NotImplementedError"
    assert verdict.reasoning.startswith("Fallback heuristic judge")
