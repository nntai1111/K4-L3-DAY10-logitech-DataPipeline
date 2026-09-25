"""app/research.py: the agent's filter tools, the date and accent helpers, and the ReAct trace.

The four tools are built by `build_research_agent` with `build_llm` and `create_agent` replaced,
so no model is ever constructed; the captured tools are then invoked directly. The tool tests run
against a real ChromaDB index built in a temp project from the committed snapshot (one author's
name given Vietnamese diacritics), so they are marked slow. `ask_agent` is fed a scripted message
list and resolves its sources through the suite's FakeIndex, so it needs no index at all.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.config import load_settings
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import load_raw_records
from pipelines.live_ingest import IngestResult
from retrieval.index import LocalEmbeddingIndex

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:  # app/ is not a package; streamlit runs it as a script folder
    sys.path.append(str(APP_DIR))

import research  # noqa: E402

RUN_DAY = date(2026, 9, 25)
# In the snapshot this paper is by "Son Nguyen, Thuy Doan"; the test corpus spells them the Vietnamese way.
ACCENTED_DOI = "10.1145/3637528.3671822"
ACCENTED_AUTHORS = ["Sơn Nguyễn", "Thùy Doãn"]
PLAIN_TWIN_DOI = "10.1145/3637528.3671810"  # the same two authors, written without diacritics
FILTER_TOOLS = {"semantic_search_papers", "lookup_paper", "find_papers_by_author", "find_papers_by_date"}


# --- _fold and _day_bound ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "folded"),
    [("Nguyễn", "nguyen"), ("NGUYỄN", "nguyen"), ("Minh Nguyen", "minh nguyen"), ("Thùy Doãn", "thuy doan"), ("", ""), (None, "")],
    ids=["accented", "accented-upper", "plain", "two-words", "empty", "none"],
)
def test_fold_drops_case_and_accents(text, folded):
    assert research._fold(text) == folded


def test_fold_lets_an_unaccented_surname_find_the_accented_one():
    assert "nguyen" in research._fold("Sơn Nguyễn, Thùy Doãn")
    assert research._fold("nguyen") in research._fold("SƠN NGUYỄN")


def test_fold_maps_d_with_stroke_to_d():
    assert research._fold("Đoàn Đặng") == "doan dang"


@pytest.mark.parametrize(
    ("value", "lower", "upper"),
    [
        ("2026", date(2026, 1, 1), date(2026, 12, 31)),
        (" 2026 ", date(2026, 1, 1), date(2026, 12, 31)),
        ("2026-02", date(2026, 2, 1), date(2026, 2, 28)),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 29)),
        ("2026-12", date(2026, 12, 1), date(2026, 12, 31)),
        ("2026-06-15", date(2026, 6, 15), date(2026, 6, 15)),
        ("last year", None, None),
        ("", None, None),
        (None, None, None),
        ("2026-13", None, None),
        ("2026-00", None, None),
        ("2026-02-30", None, None),
        ("2026-6", None, None),
        ("06/2026", None, None),
    ],
    ids=["year", "year-padded", "feb", "feb-leap", "december", "day", "words", "empty", "none", "month-13", "month-0", "feb-30", "one-digit-month", "slashes"],
)
def test_day_bound_covers_the_whole_period(value, lower, upper):
    assert research._day_bound(value, upper=False) == lower
    assert research._day_bound(value, upper=True) == upper


# --- Tool wiring (no index, no model) ----------------------------------------------------------


@pytest.fixture
def captured_agents(monkeypatch) -> list[dict]:
    built: list[dict] = []
    monkeypatch.setattr(research, "build_llm", lambda *_args, **_kwargs: "no-llm")
    monkeypatch.setattr(research, "create_agent", lambda **kwargs: built.append(kwargs) or kwargs)
    return built


def test_a_plain_index_gets_exactly_the_four_read_tools(settings, fake_index, captured_agents):
    kwargs = research.build_research_agent(settings, fake_index)

    assert [tool.name for tool in kwargs["tools"]] == ["semantic_search_papers", "lookup_paper", "find_papers_by_author", "find_papers_by_date"]
    assert kwargs["system_prompt"] == research.SYSTEM_PROMPT
    assert research.LIVE_PROMPT not in kwargs["system_prompt"]
    assert kwargs["model"] == "no-llm" and kwargs["name"] == "paper_research_agent"


def test_the_live_collection_adds_the_ingest_tool_and_prompt(settings, monkeypatch, fake_index, captured_agents):
    monkeypatch.setattr(research, "open_live_collection", lambda _settings: fake_index)

    kwargs = research.build_research_agent(settings, research.LiveCollection(settings))

    names = [tool.name for tool in kwargs["tools"]]
    assert len(names) == 5 and set(names) == FILTER_TOOLS | {"ingest_new_papers"}
    assert kwargs["system_prompt"].endswith(research.LIVE_PROMPT)
    assert kwargs["system_prompt"].startswith(research.SYSTEM_PROMPT)


# --- The filter tools against a real index (slow) ----------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory, make_project, apply_env):
    """A real Chroma index of the snapshot, one author pair accented, and the agent's tools over it."""
    with pytest.MonkeyPatch.context() as patcher:
        apply_env(patcher)
        project = make_project(tmp_path_factory.mktemp("research_tools"))
        settings = load_settings(project)
        records = [
            replace(record, authors=ACCENTED_AUTHORS) if record.paper_id.lower() == ACCENTED_DOI else record
            for record in load_raw_records(settings.paths.raw_records_json)
        ]
        table = build_clean_dataframe(records, RUN_DAY)
        index = LocalEmbeddingIndex.build(table, settings)
        patcher.setattr(research, "build_llm", lambda *_args, **_kwargs: "no-llm")
        patcher.setattr(research, "create_agent", lambda **kwargs: kwargs)
        agent_kwargs = research.build_research_agent(settings, index)
    assert settings.paths.chroma_dir.is_relative_to(project), "the index must live in the temp project"
    return SimpleNamespace(
        table=table,
        index=index,
        tools={tool.name: tool for tool in agent_kwargs["tools"]},
        published={row["paper_id"]: row["published"] for row in table.to_dict(orient="records")},
    )


def _papers(text: str) -> list[tuple[str, float | None]]:
    """(paper_id, score or None) for every paper block a tool returned, in order."""
    return [(paper_id, float(score) if score else None) for paper_id, score in research.PAPER_BLOCK.findall(text)]


def _by_surname(table, surname: str) -> list[str]:
    """DOIs of the rows with an author whose last name is `surname`, newest first (the table's order)."""
    wanted = research._fold(surname)
    return [row["paper_id"] for row in table.to_dict(orient="records") if any(research._fold(name).split()[-1] == wanted for name in row["authors"])]


def _in_window(corpus, lower: date | None, upper: date | None) -> list[str]:
    return [
        paper_id
        for paper_id, published in sorted(corpus.published.items(), key=lambda item: item[1], reverse=True)
        if (lower is None or date.fromisoformat(published) >= lower) and (upper is None or date.fromisoformat(published) <= upper)
    ]


@pytest.mark.slow
def test_author_tool_finds_a_surname_from_the_table_newest_first(corpus):
    surname = corpus.table.loc[corpus.table["paper_id"] == "10.1145/3637528.3671801", "authors"].iloc[0][0].split()[-1]
    expected = _by_surname(corpus.table, surname)
    assert surname == "Nguyen" and len(expected) == 4

    text = corpus.tools["find_papers_by_author"].invoke({"author": surname})

    assert text.startswith(f"4 paper(s) by '{surname}', newest first:\n\n")
    papers = _papers(text)
    assert [paper_id for paper_id, _ in papers] == expected
    assert all(score is None for _, score in papers), "a metadata filter has no similarity score"
    dates = [corpus.published[paper_id] for paper_id, _ in papers]
    assert dates == sorted(dates, reverse=True)
    for paper_id, _ in papers:
        assert f"published: {corpus.published[paper_id]}" in text


@pytest.mark.slow
@pytest.mark.parametrize("query", ["nguyen", "NGUYEN", "Nguyễn", "NGUYỄN"])
def test_author_tool_ignores_case_and_accents(corpus, query):
    papers = [paper_id for paper_id, _ in _papers(corpus.tools["find_papers_by_author"].invoke({"author": query}))]
    assert ACCENTED_DOI in papers and PLAIN_TWIN_DOI in papers
    assert papers == _by_surname(corpus.table, "Nguyen")


@pytest.mark.slow
def test_author_tool_matches_an_accented_full_name_written_plainly(corpus):
    text = corpus.tools["find_papers_by_author"].func("Thuy Doan")
    assert [paper_id for paper_id, _ in _papers(text)] == [ACCENTED_DOI, PLAIN_TWIN_DOI]
    assert "authors: Sơn Nguyễn, Thùy Doãn" in text, "the block shows the name as the corpus spells it"


@pytest.mark.slow
@pytest.mark.parametrize("name", ["Zzyzx Quux", "", "   "])
def test_author_tool_with_no_match_says_so(corpus, name):
    assert corpus.tools["find_papers_by_author"].invoke({"author": name}) == f"No paper in the collection has an author matching '{name}'."


@pytest.mark.slow
def test_author_tool_matches_whole_names_only(corpus):
    papers = [paper_id for paper_id, _ in _papers(corpus.tools["find_papers_by_author"].invoke({"author": "Do"}))]
    assert papers == _by_surname(corpus.table, "Do")  # Bao Do's two papers, not Thuy Doan's


@pytest.mark.slow
@pytest.mark.parametrize(
    ("after", "before", "lower", "upper"),
    [
        ("2026-04-18", "2026-05-14", date(2026, 4, 18), date(2026, 5, 14)),
        ("2026-07", "2026-07", date(2026, 7, 1), date(2026, 7, 31)),
        ("2026-05", "2026-05-02", date(2026, 5, 1), date(2026, 5, 2)),
    ],
    ids=["days-inclusive", "one-month", "month-to-day"],
)
def test_date_tool_returns_only_papers_in_the_window_newest_first(corpus, after, before, lower, upper):
    expected = _in_window(corpus, lower, upper)
    assert 0 < len(expected) <= 8

    text = corpus.tools["find_papers_by_date"].invoke({"published_after": after, "published_before": before})

    assert text.startswith(f"{len(expected)} paper(s) published from {lower} to {upper}:\n\n")
    papers = _papers(text)
    assert [paper_id for paper_id, _ in papers] == expected
    assert all(score is None for _, score in papers)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("args", "lower", "upper", "window"),
    [
        ({"published_after": "2026-07-01"}, date(2026, 7, 1), None, "2026-07-01 to today"),
        ({"published_before": "2026-04-30"}, None, date(2026, 4, 30), "the beginning to 2026-04-30"),
        ({"published_after": "last year", "published_before": "2026-04-30"}, None, date(2026, 4, 30), "the beginning to 2026-04-30"),
    ],
    ids=["after-only", "before-only", "unparseable-bound-is-open"],
)
def test_date_tool_accepts_open_ended_ranges(corpus, args, lower, upper, window):
    expected = _in_window(corpus, lower, upper)

    text = corpus.tools["find_papers_by_date"].invoke(args)

    assert text.startswith(f"{len(expected)} paper(s) published from {window}:")
    assert [paper_id for paper_id, _ in _papers(text)] == expected


@pytest.mark.slow
def test_date_tool_with_a_topic_ranks_in_window_papers_by_score(corpus):
    june = set(_in_window(corpus, date(2026, 6, 1), date(2026, 6, 30)))

    text = corpus.tools["find_papers_by_date"].invoke({"published_after": "2026-06", "published_before": "2026-06", "topic": "data quality gates"})

    papers = _papers(text)
    assert 0 < len(papers) <= 8
    assert text.startswith(f"{len(june)} paper(s) published from 2026-06-01 to 2026-06-30, showing the {len(papers)} most relevant:")
    assert {paper_id for paper_id, _ in papers} <= june
    scores = [score for _, score in papers]
    assert all(score is not None and 0.0 <= score <= 1.0 for score in scores)
    assert scores == sorted(scores, reverse=True), "ranked by relevance, not by date"
    assert text.count("\nscore: ") == len(papers)


@pytest.mark.slow
@pytest.mark.parametrize("topic", ["", "data quality gates"], ids=["no-topic", "topic"])
def test_date_tool_with_an_empty_window_says_so(corpus, topic):
    text = corpus.tools["find_papers_by_date"].invoke({"published_after": "2025", "published_before": "2025", "topic": topic})
    assert text == "No paper in the collection was published from 2025-01-01 to 2025-12-31."


@pytest.mark.slow
def test_date_tool_header_counts_every_paper_in_the_window(corpus):
    june = _in_window(corpus, date(2026, 6, 1), date(2026, 6, 30))
    assert len(june) == 15
    text = corpus.tools["find_papers_by_date"].invoke({"published_after": "2026-06", "published_before": "2026-06"})
    assert text.startswith("15 paper(s) published from 2026-06-01 to 2026-06-30")


# --- ask_agent: the ReAct trace and the sources panel ------------------------------------------


class ScriptedAgent:
    """Returns a fixed message list after the question, as a LangChain agent's invoke() would."""

    def __init__(self, messages: list):
        self.messages = messages
        self.payloads: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"messages": [HumanMessage(content=payload["messages"][0]["content"]), *self.messages]}


def _blocks(fake_index, paper_ids, scores=None) -> str:
    """Paper blocks in the filter tools' format (score lines only when scores are given)."""
    scores = scores or [None] * len(paper_ids)
    return "\n\n".join(research._paper_block(fake_index.lookup(paper_id), score) for paper_id, score in zip(paper_ids, scores))


def _search_text(fake_index, paper_ids, scores) -> str:
    """semantic_search_papers' format."""
    blocks = []
    for paper_id, score in zip(paper_ids, scores):
        document = fake_index.lookup(paper_id)
        blocks.append(f"paper_id: {paper_id}\ntitle: {document['title']}\nscore: {score:.4f}\n{document['content']}")
    return "\n\n".join(blocks)


def _lookup_text(fake_index, paper_id) -> str:
    """lookup_paper's format: no score line."""
    document = fake_index.lookup(paper_id)
    return f"paper_id: {paper_id}\ntitle: {document['title']}\n{document['content']}"


@pytest.fixture
def ids(clean_df) -> SimpleNamespace:
    rows = clean_df.to_dict(orient="records")
    return SimpleNamespace(
        minh=[row["paper_id"] for row in rows if "Minh Nguyen" in row["authors_joined"]],
        july=[row["paper_id"] for row in rows if row["published"].startswith("2026-07")],
        freshness=next(row["paper_id"] for row in rows if row["title"].startswith("Freshness SLAs")),
        ghost=next(row["paper_id"] for row in rows if row["title"].startswith("Mitigating Ghost Vectors")),
    )


THOUGHT = "Tìm bài của tác giả trước, rồi lọc theo khoảng ngày."


def test_ask_agent_turns_one_multi_tool_message_into_two_steps(fake_index, ids):
    assert len(ids.minh) == 2 and len(ids.july) == 3
    final = f"Minh Nguyen có hai bài [{ids.minh[0]}], và ba bài ra trong tháng 7 [{ids.july[0]}]."
    agent = ScriptedAgent([
        AIMessage(
            content=THOUGHT,
            tool_calls=[
                {"name": "find_papers_by_author", "args": {"author": "Nguyen"}, "id": "call-author"},
                {"name": "find_papers_by_date", "args": {"published_after": "2026-06", "published_before": "2026-08"}, "id": "call-date"},
            ],
        ),
        ToolMessage(
            content="2 paper(s) by 'Nguyen', newest first:\n\n" + _blocks(fake_index, ids.minh),
            tool_call_id="call-author",
            name="find_papers_by_author",
        ),
        ToolMessage(
            content="3 paper(s) published from 2026-06-01 to 2026-08-31:\n\n" + _blocks(fake_index, ids.july),
            tool_call_id="call-date",
            name="find_papers_by_date",
        ),
        AIMessage(content=final),
    ])

    answer = research.ask_agent(agent, fake_index, "Minh Nguyen viết gì, và bài nào ra từ tháng 6 đến tháng 8?")

    assert agent.payloads == [{"messages": [{"role": "user", "content": "Minh Nguyen viết gì, và bài nào ra từ tháng 6 đến tháng 8?"}]}]
    assert answer.mode == "agent" and answer.answer == final and answer.ingests == [] and answer.error is None
    assert answer.tool_calls == ["find_papers_by_author(Nguyen)", "find_papers_by_date(sau 2026-06, trước 2026-08)"]
    assert answer.steps == [
        {"tool": "find_papers_by_author", "argument": "Nguyen", "observation": "2 bài", "thought": THOUGHT},
        {"tool": "find_papers_by_date", "argument": "sau 2026-06, trước 2026-08", "observation": "3 bài", "thought": ""},
    ]
    assert [source["paper_id"] for source in answer.sources] == ids.minh + ids.july
    assert all(source["via"] == "filter" and source["score"] is None for source in answer.sources)
    first = fake_index.lookup(ids.minh[0])["metadata"]
    assert answer.sources[0]["title"] == first["title"] and answer.sources[0]["abs_url"] == first["abs_url"]


def test_ask_agent_scores_upgrade_filter_hits_and_lookups_are_exact(fake_index, ids):
    agent = ScriptedAgent([
        AIMessage(content="", tool_calls=[{"name": "find_papers_by_author", "args": {"author": "Minh Nguyen"}, "id": "c1"}]),
        ToolMessage(content="2 paper(s) by 'Minh Nguyen', newest first:\n\n" + _blocks(fake_index, ids.minh), tool_call_id="c1", name="find_papers_by_author"),
        AIMessage(
            content=[{"type": "text", "text": "Cần thêm điểm tương đồng."}],  # Gemini 3 returns typed parts
            tool_calls=[
                {"name": "semantic_search_papers", "args": {"top_k": 2, "query": "agentic rag"}, "id": "c2"},
                {"name": "lookup_paper", "args": {"paper_id_or_title": ids.ghost}, "id": "c3"},
                {"name": "find_papers_by_author", "args": {"author": "Zzyzx"}, "id": "c4"},
                {"name": "lookup_paper", "args": {"paper_id_or_title": "no such paper"}, "id": "c5"},
            ],
        ),
        ToolMessage(content=_search_text(fake_index, [ids.minh[0], ids.freshness], [0.8123, 0.5]), tool_call_id="c2", name="semantic_search_papers"),
        ToolMessage(content=_lookup_text(fake_index, ids.ghost), tool_call_id="c3", name="lookup_paper"),
        ToolMessage(content="No paper in the collection has an author matching 'Zzyzx'.", tool_call_id="c4", name="find_papers_by_author"),
        ToolMessage(content="No exact paper match found.\nsecond line is never shown", tool_call_id="c5", name="lookup_paper"),
        AIMessage(content=f"Xem [{ids.minh[0]}]."),
    ])

    answer = research.ask_agent(agent, fake_index, "agentic rag?")

    assert [step["thought"] for step in answer.steps] == ["", "Cần thêm điểm tương đồng.", "", "", ""]
    assert [step["argument"] for step in answer.steps] == ["Minh Nguyen", "agentic rag", ids.ghost, "Zzyzx", "no such paper"]
    assert [step["observation"] for step in answer.steps] == [
        "2 bài",
        "2 bài, cosine cao nhất 0.812",
        "1 bài",
        "No paper in the collection has an author matching 'Zzyzx'.",
        "No exact paper match found.",
    ]
    by_id = {source["paper_id"]: (source["score"], source["via"]) for source in answer.sources}
    assert list(by_id) == [ids.minh[0], ids.minh[1], ids.freshness, ids.ghost], "first-seen order"
    assert by_id[ids.minh[0]] == (pytest.approx(0.8123), "cosine"), "seen by the filter first, then with a score"
    assert by_id[ids.minh[1]] == (None, "filter")
    assert by_id[ids.freshness] == (pytest.approx(0.5), "cosine")
    assert by_id[ids.ghost] == (None, "exact")


def test_ask_agent_keeps_the_first_score_when_a_paper_reappears_unscored(fake_index, ids):
    paper = ids.minh[0]
    agent = ScriptedAgent([
        AIMessage(content="", tool_calls=[{"name": "semantic_search_papers", "args": {"query": "q"}, "id": "s"}]),
        ToolMessage(content=_search_text(fake_index, [paper], [0.7]), tool_call_id="s", name="semantic_search_papers"),
        AIMessage(content="", tool_calls=[{"name": "lookup_paper", "args": {"paper_id_or_title": paper}, "id": "l"}]),
        ToolMessage(content=_lookup_text(fake_index, paper), tool_call_id="l", name="lookup_paper"),
        AIMessage(content=f"[{paper}]"),
    ])

    [source] = research.ask_agent(agent, fake_index, "q").sources

    assert source["score"] == pytest.approx(0.7) and source["via"] == "cosine"


@pytest.mark.parametrize(
    ("args", "argument"),
    [
        ({"published_after": "2026-06", "published_before": "", "topic": ""}, "sau 2026-06"),
        ({"published_before": "2026-08-15"}, "trước 2026-08-15"),
        ({"topic": "freshness", "published_after": "2026"}, "chủ đề freshness, sau 2026"),
    ],
    ids=["empty-values-dropped", "before-only", "model-order-kept"],
)
def test_ask_agent_describes_a_date_call_in_words(fake_index, args, argument):
    agent = ScriptedAgent([
        AIMessage(content="", tool_calls=[{"name": "find_papers_by_date", "args": args, "id": "d"}]),
        ToolMessage(content="No paper in the collection was published from the beginning to today.", tool_call_id="d", name="find_papers_by_date"),
        AIMessage(content="Không có bài nào."),
    ])

    [step] = research.ask_agent(agent, fake_index, "q").steps

    assert step["argument"] == argument
    assert step["observation"] == "No paper in the collection was published from the beginning to today."


def test_ask_agent_shows_the_search_query_not_top_k(fake_index):
    agent = ScriptedAgent([
        AIMessage(content="", tool_calls=[{"name": "semantic_search_papers", "args": {"top_k": 3, "query": "ghost vectors"}, "id": "s"}]),
        ToolMessage(content="", tool_call_id="s", name="semantic_search_papers"),
        AIMessage(content="Không có."),
    ])

    answer = research.ask_agent(agent, fake_index, "q")

    assert answer.tool_calls == ["semantic_search_papers(ghost vectors)"] and answer.steps[0]["argument"] == "ghost vectors"
    assert answer.sources == []


def test_ask_agent_never_passes_a_thought_off_as_the_answer(fake_index, ids):
    agent = ScriptedAgent([
        AIMessage(content=THOUGHT, tool_calls=[{"name": "find_papers_by_author", "args": {"author": "Nguyen"}, "id": "a"}]),
        ToolMessage(content=_blocks(fake_index, ids.minh), tool_call_id="a", name="find_papers_by_author"),
        AIMessage(content=""),  # the model stopped without writing an answer
    ])

    assert research.ask_agent(agent, fake_index, "q").answer == ""


# --- _observation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "first_sentence"),
    [
        (IngestResult(topic="vla robots", published_since="2026-03-29", fetched=6, batch_rows=6, blocked_reason="the new batch failed freshness SLA"), "BLOCKED"),
        (IngestResult(topic="vla robots", published_since="2026-03-29", indexed=True, new_papers=0, already_indexed=5, total_papers=29), "PASSED, nothing new"),
        (
            IngestResult(
                topic="vla robots",
                published_since="2026-03-29",
                indexed=True,
                new_papers=1,
                total_papers=25,
                added=[{"paper_id": "10.9999/vla.1", "title": "A study", "published": "2026-09-10"}],
            ),
            "PASSED and indexed",
        ),
    ],
    ids=["blocked", "nothing-new", "indexed"],
)
def test_observation_of_an_ingest_is_its_first_sentence(result, first_sentence):
    assert research._observation("ingest_new_papers", result.summary()) == first_sentence


def test_observation_counts_blocks_and_reports_the_best_score():
    text = "paper_id: 10.1/a\ntitle: A\nscore: 0.4000\nx\n\npaper_id: 10.1/b\ntitle: B\nscore: 0.9126\ny"
    assert research._observation("semantic_search_papers", text) == "2 bài, cosine cao nhất 0.913"
    assert research._observation("find_papers_by_author", "1 paper(s):\n\npaper_id: 10.1/a\ntitle: A\npublished: 2026-01-01") == "1 bài"
    assert research._observation("lookup_paper", "x" * 200) == "x" * 90
