from __future__ import annotations

from langchain_core.messages import AIMessage
import pytest

from core.config import load_settings
from core.utils import read_json
from evaluation.metrics import _token_f1, evaluate_pipeline
from evaluation.testset import build_test_set
from retrieval import agent as agent_module
from retrieval.agent import build_agent, run_agent_question
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question

from conftest import ToolCallingFakeModel


@pytest.fixture
def index(settings, clean_df):
    return LocalEmbeddingIndex.build(clean_df, settings, settings.paths.embeddings_json)


def test_index_build_search_lookup_and_reload(settings, clean_df, index):
    assert index.collection_name == settings.baseline_collection_name
    assert index.collection.count() == 24
    results = index.search("freshness service-level agreements for document ingestion")
    assert len(results) == settings.top_k
    assert [result.score for result in results] == sorted((result.score for result in results), reverse=True)
    relevant = set(clean_df.loc[clean_df["summary"].str.contains("freshness service-level"), "paper_id"])
    assert results[0].paper_id in relevant

    row = clean_df.iloc[3]
    assert index.lookup(row["title"].upper())["paper_id"] == row["paper_id"]
    assert index.lookup(row["paper_id"])["title"] == row["title"]
    assert index.lookup("no such paper") is None
    assert read_json(settings.paths.embeddings_json)["persist_path"] == "data/chroma"  # portable manifest
    assert LocalEmbeddingIndex.load(settings).collection.count() == 24


def test_collection_name_follows_the_manifest_path(settings, tmp_path):
    derive = LocalEmbeddingIndex._derive_collection_name
    paths = settings.paths
    assert derive(settings, None) == "papers-baseline"
    assert derive(settings, paths.corrupted_embeddings_json) == "papers-corrupted"
    assert derive(settings, paths.repaired_embeddings_json) == "papers-repaired"
    assert derive(settings, tmp_path / "My Index.json") == "my-index"


def test_answer_question_uses_quoted_title_then_semantic_search(settings, clean_df, index):
    row = clean_df.iloc[5]
    exact = answer_question(f"Who authored the paper '{row['title']}'?", settings, index)
    assert exact.retrieved_doc_ids[0] == row["paper_id"]
    assert exact.answer == row["authors_joined"]
    assert len(exact.retrieved_doc_ids) == settings.top_k

    semantic = answer_question("Which work studies debate between verifier agents for citations?", settings, index)
    assert semantic.answer and semantic.retrieved_titles


def test_evaluate_pipeline_scores_the_clean_baseline(settings, clean_df, index):
    build_test_set(clean_df, settings.paths.eval_testset)
    bundle = evaluate_pipeline(settings, index, settings.paths.eval_testset, settings.paths.baseline_metrics, settings.paths.baseline_answers)
    assert bundle.summary["samples"] == 10
    assert bundle.summary["retrieval_hit_rate"] == 1.0
    assert bundle.summary["mean_token_f1"] == 1.0
    assert bundle.summary["judge_accuracy"] == 1.0
    assert "skipped" in bundle.summary["ragas"]
    # Clean answers match the reference verbatim, so no LLM call is spent on judging them.
    assert {answer["judge_source"] for answer in bundle.answers} == {"exact_match"}


def test_token_f1_edge_cases():
    assert _token_f1("", "anything") == 0.0
    assert _token_f1("alpha beta", "gamma delta") == 0.0
    assert _token_f1("Alpha  beta", "alpha BETA") == 1.0
    assert 0.0 < _token_f1("alpha beta gamma delta", "alpha beta") < 1.0


@pytest.mark.parametrize(
    ("provider", "env", "expected"),
    [
        ("gemini", {"GOOGLE_API_KEY": "test-key"}, "ChatGoogleGenerativeAI"),
        ("openai", {"OPENAI_API_KEY": "test-key"}, "ChatOpenAI"),
        ("anthropic", {"ANTHROPIC_API_KEY": "test-key"}, "ChatAnthropic"),
        ("Anthorpic", {"ANTHROPIC_API_KEY": "test-key"}, "ChatAnthropic"),
        ("openrouter", {"OPENROUTER_API_KEY": "test-key"}, "ChatOpenAI"),
        ("ollama", {}, "ChatOllama"),
        ("custom-llm", {"CUSTOM_LLM_BASE_URL": "http://localhost:9999/v1"}, "ChatOpenAI"),
        ("mock", {}, "FakeListChatModel"),
    ],
)
def test_build_llm_routes_every_provider(settings, monkeypatch, provider, env, expected):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert type(build_llm(load_settings(settings.paths.project_dir))).__name__ == expected


@pytest.mark.parametrize(
    ("provider", "missing"),
    [
        ("gemini", "GOOGLE_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("custom", "CUSTOM_LLM_BASE_URL"),
        ("watsonx", None),
    ],
)
def test_build_llm_rejects_missing_credentials(settings, monkeypatch, provider, missing):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    if missing:
        monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError):
        build_llm(load_settings(settings.paths.project_dir))


def test_agent_calls_both_tools_and_returns_final_answer(settings, clean_df, index, monkeypatch):
    target = clean_df.iloc[0]
    script = iter(
        [
            AIMessage(content="", tool_calls=[{"name": "semantic_search_papers", "args": {"query": "benchmark drift"}, "id": "call-1", "type": "tool_call"}]),
            AIMessage(content="", tool_calls=[{"name": "lookup_paper", "args": {"paper_id_or_title": target["paper_id"]}, "id": "call-2", "type": "tool_call"}]),
            AIMessage(content="", tool_calls=[{"name": "lookup_paper", "args": {"paper_id_or_title": "missing"}, "id": "call-3", "type": "tool_call"}]),
            AIMessage(content="Grounded answer from the corpus."),
        ]
    )
    monkeypatch.setattr(agent_module, "build_llm", lambda settings, temperature: ToolCallingFakeModel(messages=script))
    agent = build_agent(settings, index)
    result = agent.invoke({"messages": [{"role": "user", "content": "What is new in benchmark evaluation?"}]})
    tool_outputs = [message.content for message in result["messages"] if message.type == "tool"]
    assert "paper_id:" in tool_outputs[0] and "score:" in tool_outputs[0]
    assert target["title"] in tool_outputs[1]
    assert tool_outputs[2] == "No exact paper match found."
    assert result["messages"][-1].content == "Grounded answer from the corpus."


def test_run_agent_question_handles_an_empty_transcript():
    class EmptyAgent:
        def invoke(self, payload):
            return {"messages": []}

    assert run_agent_question(EmptyAgent(), "question") == ""
