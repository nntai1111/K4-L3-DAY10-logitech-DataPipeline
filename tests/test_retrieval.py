from __future__ import annotations

from dataclasses import replace
from datetime import date
import math

import pytest

from core.config import load_settings
from core.utils import first_sentence, read_json, write_json
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import load_raw_records
from retrieval import agent as agent_module
from retrieval import llm as llm_module
from retrieval.index import LocalEmbeddingIndex
from retrieval.qa import _extract_answer, answer_question

# --- qa.py: field routing and exact-title lookup -----------------------------------------------


@pytest.fixture
def first_row(clean_df):
    return clean_df.iloc[0].to_dict()


@pytest.mark.parametrize(
    ("question", "field"),
    [
        ("Who authored 'X'?", "authors_joined"),
        ("Please list the authors of 'X'.", "authors_joined"),
        ("When was 'X' published?", "published"),
        ("What is the publication date of 'X'?", "published"),
        ("Which paper was published on a Monday?", "published"),
        ("What categories does 'X' belong to?", "categories_joined"),
        ("What is the summary of the paper 'X'?", "summary"),
        ("Tell me anything about 'X'.", "summary"),
    ],
)
def test_extract_answer_routes_by_wording(first_row, make_search_result, question, field):
    answer = _extract_answer(question, make_search_result(first_row))
    if field == "summary":
        assert answer == first_sentence(first_row["summary"])
    else:
        assert answer == first_row[field]


def test_answer_question_puts_the_exact_title_first(settings, fake_index, clean_df):
    target = clean_df.iloc[7].to_dict()
    result = answer_question(f"Who authored '{target['title'].upper()}'?", settings, fake_index)
    assert result.answer == target["authors_joined"]
    assert result.retrieved_doc_ids[0] == target["paper_id"]
    assert len(result.retrieved_doc_ids) == settings.top_k
    assert len(set(result.retrieved_doc_ids)) == len(result.retrieved_doc_ids), "exact match must be de-duplicated"
    assert result.retrieved_titles[0] == target["title"]
    assert result.retrieved_contexts[0] == target["text_for_embedding"]


def test_answer_question_deduplicates_when_search_also_finds_the_title(settings, fake_index, clean_df):
    target = clean_df.iloc[0].to_dict()  # the fake search returns rows 0..3, so row 0 comes back twice
    result = answer_question(f"When was '{target['title']}' published?", settings, fake_index, top_k=2)
    assert result.retrieved_doc_ids == [target["paper_id"], clean_df.iloc[1]["paper_id"]]
    assert result.answer == target["published"]


def test_answer_question_without_a_quoted_title_uses_search_order(settings, fake_index, clean_df):
    result = answer_question("Summarise freshness work", settings, fake_index)
    assert result.retrieved_doc_ids == clean_df["paper_id"].head(4).tolist()


def test_answer_question_with_nothing_retrieved(settings, make_fake_index):
    result = answer_question("What is the summary of 'Unknown'?", settings, make_fake_index(rows=[], search_results=[]))
    assert result.answer == "I don't know from the indexed corpus."
    assert result.retrieved_doc_ids == [] and result.retrieved_contexts == []


# --- index.py: real ChromaDB + MiniLM ----------------------------------------------------------


@pytest.fixture(scope="module")
def built_index(tmp_path_factory, make_project):
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setenv("LLM_PROVIDER", "mock")
        project = make_project(tmp_path_factory.mktemp("index_project"))
        settings = load_settings(project)
        df = build_clean_dataframe(load_raw_records(settings.paths.raw_records_json), date(2026, 9, 25))
        index = LocalEmbeddingIndex.build(df, settings)
        yield settings, df, index


@pytest.mark.slow
def test_build_writes_a_portable_manifest(built_index):
    settings, df, index = built_index
    manifest = read_json(settings.paths.embeddings_json)
    assert index.collection_name == manifest["collection_name"] == settings.baseline_collection_name
    assert manifest["persist_path"] == "data/chroma"
    assert manifest["backend"] == "chroma" and manifest["embedding_model"] == settings.embedding_model
    assert len(manifest["documents"]) == len(df) == index.collection.count() == 24


@pytest.mark.slow
def test_search_ranks_the_matching_paper_first(built_index):
    _settings, df, index = built_index
    target = df.iloc[3]
    # The document's own text is its nearest neighbour; a bare title only has to land in the top k,
    # because the corpus holds near-duplicate "Advanced Perspectives on ..." papers (hence qa.py's
    # exact-title lookup).
    [best] = index.search(target["text_for_embedding"], top_k=1)
    assert best.paper_id == target["paper_id"]
    assert best.score == pytest.approx(1.0, abs=1e-3)
    results = index.search(target["title"])
    assert len(results) == 4
    assert target["paper_id"] in [result.paper_id for result in results]
    assert all(0.0 <= result.score <= 1.0 for result in results)
    assert [result.score for result in results] == sorted((result.score for result in results), reverse=True)
    assert best.metadata["authors_joined"] == target["authors_joined"]
    assert len(index.search(target["title"], top_k=2)) == 2


@pytest.mark.slow
def test_lookup_by_id_or_title(built_index):
    _settings, df, index = built_index
    row = df.iloc[5]
    assert index.lookup(row["paper_id"].upper())["paper_id"] == row["paper_id"]
    assert index.lookup(f"  {row['title'].lower()} ")["paper_id"] == row["paper_id"]
    assert index.lookup("no such paper") is None


@pytest.mark.slow
def test_load_round_trips_the_manifest(built_index):
    settings, _df, index = built_index
    loaded = LocalEmbeddingIndex.load(settings)
    assert loaded.collection_name == index.collection_name
    assert loaded.persist_path == settings.paths.project_dir / "data" / "chroma"
    assert loaded.documents == index.documents
    assert loaded.collection.count() == 24


@pytest.mark.slow
def test_load_accepts_an_absolute_persist_path(built_index, tmp_path):
    settings, _df, _index = built_index
    manifest = read_json(settings.paths.embeddings_json)
    manifest["persist_path"] = str(settings.paths.chroma_dir.resolve())
    moved = tmp_path / "manifest.json"
    write_json(moved, manifest)
    loaded = LocalEmbeddingIndex.load(settings, moved)
    assert loaded.persist_path == settings.paths.chroma_dir.resolve()


@pytest.mark.slow
def test_rebuilding_replaces_the_collection(built_index):
    settings, df, _index = built_index
    rebuilt = LocalEmbeddingIndex.build(df.head(6), settings, settings.paths.corrupted_embeddings_json)
    assert rebuilt.collection_name == settings.corrupted_collection_name
    assert rebuilt.collection.count() == 6
    again = LocalEmbeddingIndex.build(df.head(3), settings, settings.paths.corrupted_embeddings_json)
    assert again.collection.count() == 3, "no stale vectors may survive a rebuild"


@pytest.mark.slow
def test_embeddings_are_normalised(built_index):
    _settings, _df, index = built_index
    [vector] = index.embedding_model.embed_documents(["hello world"])
    query = index.embedding_model.embed_query("hello world")
    assert len(vector) == 384
    assert math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-4)
    assert query == pytest.approx(vector, abs=1e-5)


def test_collection_name_derivation(settings):
    derive = LocalEmbeddingIndex._derive_collection_name
    paths = settings.paths
    assert derive(settings, None) == settings.baseline_collection_name
    assert derive(settings, paths.embeddings_json) == settings.baseline_collection_name
    assert derive(settings, paths.corrupted_embeddings_json) == settings.corrupted_collection_name
    assert derive(settings, paths.repaired_embeddings_json) == settings.repaired_collection_name
    assert derive(settings, paths.project_dir / "data" / "embeddings" / "My Custom_Index.json") == "my-custom-index"


def test_documents_get_unique_record_ids_even_for_duplicate_papers(clean_df):
    import pandas as pd

    doubled = pd.concat([clean_df.head(2), clean_df.head(2)], ignore_index=True)
    documents = LocalEmbeddingIndex._build_documents(doubled)
    assert len({document["record_id"] for document in documents}) == 4
    assert documents[0]["record_id"] == f"{clean_df.iloc[0]['paper_id']}::0"
    assert set(documents[0]["metadata"]) == {"paper_id", "title", "published", "authors_joined", "categories_joined", "summary", "abs_url", "pdf_url"}


# --- llm.py: provider wiring (constructors replaced, so nothing touches the network) -----------


class Recorder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.mark.parametrize(
    ("provider", "overrides", "constructor", "expected"),
    [
        ("gemini", {"google_api_key": "g"}, "ChatGoogleGenerativeAI", {"google_api_key": "g"}),
        ("openai", {"openai_api_key": "o"}, "ChatOpenAI", {"api_key": "o"}),
        ("anthropic", {"anthropic_api_key": "a"}, "ChatAnthropic", {"api_key": "a"}),
        ("Anthorpic", {"anthropic_api_key": "a"}, "ChatAnthropic", {"api_key": "a"}),
        ("openrouter", {"openrouter_api_key": "r"}, "ChatOpenAI", {"api_key": "r", "base_url": "https://openrouter.ai/api/v1"}),
        ("ollama", {}, "ChatOllama", {"base_url": "http://localhost:11434"}),
        ("custom", {"custom_llm_base_url": "http://llm.local/v1"}, "ChatOpenAI", {"api_key": "unused", "base_url": "http://llm.local/v1"}),
        ("Custom-LLM", {"custom_llm_base_url": "http://llm.local/v1", "custom_llm_api_key": "k"}, "ChatOpenAI", {"api_key": "k"}),
    ],
)
def test_build_llm_wires_each_provider(settings, monkeypatch, provider, overrides, constructor, expected):
    for name in ("ChatGoogleGenerativeAI", "ChatOpenAI", "ChatAnthropic", "ChatOllama"):
        monkeypatch.setattr(llm_module, name, type(name, (Recorder,), {}))
    configured = replace(settings, llm_provider=provider, model_name="model-x", **overrides)

    built = llm_module.build_llm(configured, temperature=0.3)

    assert type(built).__name__ == constructor
    assert built.kwargs["model"] == "model-x"
    assert built.kwargs["temperature"] == 0.3
    for key, value in expected.items():
        assert built.kwargs[key] == value


def test_build_llm_mock_returns_a_fake_chat_model(settings):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    model = llm_module.build_llm(settings)
    assert isinstance(model, FakeListChatModel)
    assert "mock response" in model.invoke("hi").content


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic", "openrouter", "custom", "nonsense"])
def test_build_llm_refuses_missing_credentials(settings, provider):
    with pytest.raises(RuntimeError):
        llm_module.build_llm(replace(settings, llm_provider=provider))


# --- agent.py: tools and answer extraction (agent factory replaced) ----------------------------


def test_build_agent_exposes_search_and_lookup_tools(settings, monkeypatch, fake_index, clean_df):
    captured = {}
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: captured.update(kwargs) or "agent")

    assert agent_module.build_agent(settings, fake_index) == "agent"
    tools = {tool.name: tool for tool in captured["tools"]}
    assert set(tools) == {"semantic_search_papers", "lookup_paper"}
    assert captured["name"] == "paper_corpus_agent"
    assert "Crossref" in captured["system_prompt"]

    search_output = tools["semantic_search_papers"].invoke({"query": "rag", "top_k": 2})
    assert search_output.count("paper_id: ") == 2
    assert clean_df.iloc[0]["paper_id"] in search_output
    assert "score: 0.5000" in search_output
    assert fake_index.search_calls[-1] == ("rag", 2)

    row = clean_df.iloc[4]
    found = tools["lookup_paper"].invoke({"paper_id_or_title": row["title"]})
    assert found.startswith(f"paper_id: {row['paper_id']}\ntitle: {row['title']}\n")
    assert tools["lookup_paper"].invoke({"paper_id_or_title": "missing"}) == "No exact paper match found."


class _Message:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    def invoke(self, payload):
        self.inputs.append(payload)
        return self.result


def test_run_agent_question_returns_the_final_message():
    agent = _Agent({"messages": [_Message("thinking"), _Message("final answer")]})
    assert agent_module.run_agent_question(agent, "Why?") == "final answer"
    assert agent.inputs == [{"messages": [{"role": "user", "content": "Why?"}]}]


def test_run_agent_question_handles_empty_and_plain_messages():
    assert agent_module.run_agent_question(_Agent({}), "q") == ""
    assert agent_module.run_agent_question(_Agent({"messages": ["plain text"]}), "q") == "plain text"


def test_run_agent_question_joins_typed_content_parts():
    parts = [{"type": "text", "text": "Hello "}, {"type": "tool_use", "id": "x"}, {"type": "text", "text": "world "}, 42]
    assert agent_module.run_agent_question(_Agent({"messages": [_Message(parts)]}), "q") == "Hello world 42"
