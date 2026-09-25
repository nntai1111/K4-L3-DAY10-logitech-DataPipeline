"""Live ingest: one topic through fetch, row quarantine, the quality gate, merge and the Live index.

Crossref is never called. `pipelines.live_ingest._fetch_live_payload` is replaced by a fake that
returns a crafted payload (or raises), and the clock is pinned to the suite's run date, so every
paper's age is the same on any day. Everything the pipeline writes lands under the temp
project's data/live/. Tests that embed with the real MiniLM model are marked slow.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest
import requests
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.utils import read_json
from pipelines import live_ingest
from pipelines.live_ingest import (
    IngestResult,
    ingest_history,
    ingest_topic,
    live_dir,
    live_paper_count,
    live_settings,
    open_live_collection,
    quarantine_reason,
    reset_live_collection,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:  # app/ is not a package; streamlit runs it as a script folder
    sys.path.append(str(APP_DIR))

import research  # noqa: E402

SNAPSHOT_PAPERS = 24
TOPIC = "vla robots"
VLA_QUERY = "vision-language-action robot arm grasping household objects"


# --- Crafted Crossref payloads -----------------------------------------------------------------


def _item(doi: str, title: str, *, published: tuple[int, int, int] = (2026, 9, 10), abstract: str | None = None) -> dict:
    abstract = abstract or (
        "We train a vision-language-action model that maps camera images and spoken instructions to "
        f"robot arm motions, and measure grasp success on household objects ({doi})."
    )
    return {
        "DOI": doi,
        "title": [title],
        "abstract": f"<jats:p>{abstract}</jats:p>",
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "subject": ["Robotics"],
        "published": {"date-parts": [list(published)]},
        "URL": f"https://doi.org/{doi}",
    }


def _payload(*items: dict) -> dict:
    return {"message": {"items": list(items)}}


def _vla_papers(count: int, published: tuple[int, int, int] = (2026, 9, 10)) -> list[dict]:
    return [
        _item(f"10.9999/vla.{number}", f"Vision-language-action policies for robot manipulation, study {number}", published=published)
        for number in range(1, count + 1)
    ]


def _stale_batch() -> list[dict]:
    """Five papers from 2025 and one fresh one: 83% of the batch is past the 180-day SLA."""
    old = [_item(f"10.9999/old.{number}", f"Robot learning from demonstrations, part {number}", published=(2025, 6, 1)) for number in range(1, 6)]
    return old + _vla_papers(1)


NEW_DOIS = {f"10.9999/vla.{number}" for number in range(1, 6)}


# --- Fixtures ----------------------------------------------------------------------------------


class Clock:
    """Noon UTC on the run date, one second later on every call, so each run's log name is unique."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


class FakeCrossref:
    """Stands in for the live fetch: returns `payload` or raises `error`, and keeps each query."""

    def __init__(self):
        self.payload: dict = _payload()
        self.error: Exception | None = None
        self.calls: list = []

    def __call__(self, query_settings):
        self.calls.append(query_settings)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.payload)


@pytest.fixture
def clock(monkeypatch, run_date) -> Clock:
    fake = Clock(datetime(run_date.year, run_date.month, run_date.day, 12, tzinfo=UTC))
    monkeypatch.setattr(live_ingest, "now_utc", fake)
    return fake


@pytest.fixture
def crossref(monkeypatch, clock) -> FakeCrossref:
    fake = FakeCrossref()
    monkeypatch.setattr(live_ingest, "_fetch_live_payload", fake)
    return fake


def _official_files(settings) -> dict[str, bytes]:
    """Every file under data/ except data/live/, by path, with its bytes."""
    data_dir = settings.paths.project_dir / "data"
    live = live_dir(settings)
    return {
        path.relative_to(data_dir).as_posix(): path.read_bytes()
        for path in data_dir.rglob("*")
        if path.is_file() and live not in path.parents
    }


# --- Paths and row rules (no embedding) --------------------------------------------------------


def test_live_writes_are_redirected_under_the_temp_project(settings):
    live = live_dir(settings)
    redirected = live_settings(settings)
    assert live == settings.paths.project_dir / "data" / "live"
    assert not live.is_relative_to(REPO_ROOT)
    assert redirected.paths.quality_dir == live / "quality"
    assert redirected.paths.chroma_dir == live / "chroma"
    assert redirected.paths.raw_records_json == settings.paths.raw_records_json


GOOD_ROW = {
    "paper_id": "10.9999/row",
    "title": "A perfectly ordinary paper title",
    "summary": "An abstract that is comfortably longer than thirty characters.",
    "text_for_embedding": "Title: A perfectly ordinary paper title",
}


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({}, None),
        ({"paper_id": ""}, "missing paper_id, title or text"),
        ({"title": ""}, "missing paper_id, title or text"),
        ({"summary": "Too short to keep."}, "summary under 30 characters"),
        ({"title": "VLA bot"}, "title under 10 characters"),
        ({"summary": "We bound the sample cost by $${\\mathcal{O}}(d)$$ for every task."}, "junk symbols in summary ($${\\)"),
    ],
    ids=["good", "no-id", "no-title", "short-summary", "short-title", "leaked-latex"],
)
def test_quarantine_reason_applies_the_row_rules(overrides, reason):
    assert quarantine_reason(GOOD_ROW | overrides) == reason


# --- Blocked runs (the gate stops before anything is embedded) ---------------------------------


def test_stale_batch_is_blocked_by_freshness(settings, crossref):
    crossref.payload = _payload(*_stale_batch())
    result, index = ingest_topic(settings, TOPIC)

    assert index is None and result.indexed is False
    assert result.fetched == result.batch_rows == 6
    assert result.batch_gate_passed is False and result.batch_failed == []
    assert result.batch_stale_ratio == pytest.approx(5 / 6, abs=1e-3)
    assert "freshness SLA (83% of the batch is older than 180 days, limit 25%)" in result.blocked_reason
    assert result.merged_gate_passed is None and result.new_papers == 0
    assert live_paper_count(settings) is None
    assert not (live_dir(settings) / "chroma").exists()


def test_too_few_papers_are_blocked_by_row_count(settings, crossref):
    crossref.payload = _payload(*_vla_papers(3))
    result, index = ingest_topic(settings, TOPIC)

    assert index is None and result.indexed is False
    assert result.batch_rows == 3
    assert result.batch_failed == ["expect_table_row_count_to_be_between"]
    assert result.blocked_reason == "the new batch failed expect_table_row_count_to_be_between"
    assert live_paper_count(settings) is None


@pytest.mark.parametrize(
    "payload",
    [{}, _payload(), _payload(_item("10.9999/no-abstract", "A paper that lost its abstract") | {"abstract": ""})],
    ids=["no-message", "no-items", "no-usable-items"],
)
def test_payload_without_usable_papers_is_blocked(settings, crossref, payload):
    crossref.payload = payload
    result, index = ingest_topic(settings, TOPIC)

    assert index is None and result.indexed is False
    assert result.blocked_reason == "Crossref returned no usable papers for this topic and date range"
    assert result.batch_rows == 0 and result.batch_gate_passed is None
    assert result.summary().startswith("BLOCKED.")


def test_fetch_failure_is_blocked_and_logged(settings, crossref):
    crossref.error = requests.ConnectionError("no network")
    result, index = ingest_topic(settings, TOPIC)

    assert index is None and result.indexed is False
    assert result.blocked_reason == "Crossref could not be reached (ConnectionError)"
    assert result.fetched == 0
    assert not (live_dir(settings) / "raw").exists(), "a failed fetch has no response to save"
    [entry] = ingest_history(settings)
    assert entry["blocked_reason"] == result.blocked_reason and entry["topic"] == TOPIC
    assert live_paper_count(settings) is None


def test_fresh_batch_is_blocked_when_the_merged_table_would_be_stale(settings, crossref, clock):
    # A year on, every snapshot paper is past the SLA, so 24 of the 29 merged rows are stale.
    clock.now = datetime(2027, 6, 1, 12, tzinfo=UTC)
    crossref.payload = _payload(*_vla_papers(5, published=(2027, 5, 20)))
    result, index = ingest_topic(settings, TOPIC)

    assert index is None and result.indexed is False
    assert result.batch_gate_passed is True and result.merged_gate_passed is False
    assert result.blocked_reason == "the merged collection would fail freshness SLA"
    assert result.total_papers == SNAPSHOT_PAPERS
    assert live_paper_count(settings) is None


@pytest.mark.parametrize(
    ("given", "expected"),
    [("2025-01-01", "2025-01-01"), (" 2025-03 ", "2025-03"), ("last year", None), ("01/02/2025", None), ("", None), (None, None)],
    ids=["iso-day", "iso-month-padded", "words", "slashes", "empty", "none"],
)
def test_published_since_reaches_the_crossref_filter(settings, crossref, given, expected):
    ingest_topic(settings, f"  {TOPIC} ", published_since=given, max_results=7)

    [query] = crossref.calls
    assert query.source_query == TOPIC and query.max_results == 7
    if expected:
        assert query.source_filter == f"from-pub-date:{expected},has-abstract:true"
    else:
        assert query.source_filter == settings.source_filter, "anything but an ISO date falls back to the default window"


# --- Summary wording ---------------------------------------------------------------------------


def test_summary_of_a_passed_ingest_repeats_the_numbers():
    result = IngestResult(
        topic=TOPIC,
        published_since="2026-03-29",
        fetched=7,
        batch_rows=7,
        quarantined=[{"paper_id": "10.9999/junk", "title": "Junk", "reason": "junk symbols in summary ($${\\)"}],
        already_indexed=1,
        new_papers=5,
        total_papers=29,
        indexed=True,
        added=[{"paper_id": "10.9999/vla.1", "title": "VLA study one", "published": "2026-09-10"}],
    )
    text = result.summary()
    assert text.startswith("PASSED and indexed.")
    for fragment in (
        "Crossref returned 7 items on 'vla robots' (published since 2026-03-29); 7 survived cleaning.",
        "1 were quarantined by row checks (10.9999/junk: junk symbols in summary",
        "5 were new (1 already in the collection)",
        "The collection now holds 29 papers.",
        "- 10.9999/vla.1 | 2026-09-10 | VLA study one",
    ):
        assert fragment in text


def test_summary_of_a_blocked_ingest_gives_the_reason():
    result = IngestResult(topic=TOPIC, published_since="2025-01-01", fetched=6, batch_rows=6, blocked_reason="the new batch failed freshness SLA")
    text = result.summary()
    assert text.startswith("BLOCKED.")
    assert "'vla robots' (published since 2025-01-01) was stopped: the new batch failed freshness SLA." in text
    assert "Crossref returned 6 items, 6 survived cleaning." in text
    assert text.endswith("Nothing was indexed; the collection is unchanged.")


# --- Indexed runs (real ChromaDB + MiniLM) -----------------------------------------------------


@pytest.mark.slow
def test_fresh_batch_is_gated_merged_and_indexed(settings, crossref):
    crossref.payload = _payload(*_vla_papers(5))
    official_before = _official_files(settings)

    result, index = ingest_topic(settings, TOPIC)

    assert result.indexed is True and result.blocked_reason is None
    assert result.fetched == result.batch_rows == 5 and result.quarantined == []
    assert result.batch_gate_passed is True and result.merged_gate_passed is True
    assert result.new_papers == 5 and result.already_indexed == 0
    assert result.total_papers == SNAPSHOT_PAPERS + 5
    assert {paper["paper_id"] for paper in result.added} == NEW_DOIS
    assert result.summary().startswith("PASSED and indexed.") and "now holds 29 papers" in result.summary()

    assert index.collection_name == "papers-live" and index.collection.count() == 29
    assert index.search(VLA_QUERY, top_k=1)[0].paper_id in NEW_DOIS
    assert index.lookup("10.9999/vla.3")["title"] == "Vision-language-action policies for robot manipulation, study 3"
    assert live_paper_count(settings) == 29

    live = live_dir(settings)
    [log] = (live / "ingest_log").glob("*.json")
    assert read_json(log)["new_papers"] == 5 and read_json(log)["topic"] == TOPIC
    [raw] = (live / "raw").glob("*.json")
    assert read_json(raw) == crossref.payload
    assert _official_files(settings) == official_before, "data/raw and every other official file stay byte-identical"


@pytest.mark.slow
def test_reingesting_the_same_batch_adds_nothing(settings, crossref):
    crossref.payload = _payload(*_vla_papers(5))
    ingest_topic(settings, TOPIC)

    result, index = ingest_topic(settings, TOPIC)

    assert result.indexed is True and index is None, "nothing new means nothing to rebuild"
    assert result.new_papers == 0 and result.already_indexed == 5 and result.added == []
    assert result.total_papers == 29 == live_paper_count(settings)
    assert result.summary().startswith("PASSED, nothing new.")
    assert "all 5 were already in the collection (29 papers)" in result.summary()
    assert [entry["new_papers"] for entry in ingest_history(settings)] == [0, 5], "history is newest first"


@pytest.mark.slow
def test_rows_breaking_a_row_rule_are_quarantined_and_the_rest_indexed(settings, crossref):
    junk = _item(
        "10.9999/junk",
        "Sample complexity of embodied transformers",
        abstract="We bound the sample cost by $${\\mathcal{O}}(d)$$ for every task family considered here.",
    )
    short = _item("10.9999/short", "VLA bot")
    crossref.payload = _payload(*_vla_papers(5), junk, short)

    result, index = ingest_topic(settings, TOPIC)

    reasons = {row["paper_id"]: row["reason"] for row in result.quarantined}
    assert reasons.keys() == {"10.9999/junk", "10.9999/short"}
    assert reasons["10.9999/junk"].startswith("junk symbols in summary ($${")
    assert reasons["10.9999/short"] == "title under 10 characters"
    assert result.fetched == result.batch_rows == 7
    assert result.indexed is True and result.new_papers == 5 and result.total_papers == 29
    assert index.lookup("10.9999/junk") is None and index.lookup("10.9999/short") is None
    assert "2 were quarantined by row checks" in result.summary()


@pytest.mark.slow
def test_blocked_ingests_leave_an_open_collection_unchanged(settings, crossref):
    index = open_live_collection(settings)
    assert index.collection.count() == live_paper_count(settings) == SNAPSHOT_PAPERS

    for payload, error in [(_payload(*_stale_batch()), None), (_payload(*_vla_papers(3)), None), (None, requests.ConnectionError("down"))]:
        crossref.payload, crossref.error = payload, error
        result, new_index = ingest_topic(settings, TOPIC)
        assert result.indexed is False and new_index is None
        assert index.collection.count() == live_paper_count(settings) == SNAPSHOT_PAPERS
        assert index.lookup("10.9999/vla.1") is None


@pytest.mark.slow
def test_open_live_collection_seeds_from_the_snapshot_then_reloads(settings, crossref):
    seeded = open_live_collection(settings)
    assert seeded.collection_name == "papers-live" and seeded.collection.count() == SNAPSHOT_PAPERS
    assert seeded.persist_path == live_dir(settings) / "chroma"

    crossref.payload = _payload(*_vla_papers(5))
    ingest_topic(settings, TOPIC)
    reopened = open_live_collection(settings)
    assert reopened.collection.count() == 29 and reopened.lookup("10.9999/vla.5") is not None


@pytest.mark.slow
def test_reset_returns_the_collection_to_the_snapshot(settings, crossref):
    crossref.payload = _payload(*_vla_papers(5))
    ingest_topic(settings, TOPIC)

    index = reset_live_collection(settings)

    assert index.collection.count() == SNAPSHOT_PAPERS == live_paper_count(settings)
    assert index.lookup("10.9999/vla.1") is None
    assert len(ingest_history(settings)) == 1, "reset keeps the ingest log"
    assert list((live_dir(settings) / "raw").glob("*.json")), "reset keeps the raw responses"


# --- app/research.py: the LiveCollection handle and the agent wiring ---------------------------


@pytest.fixture
def captured_agents(monkeypatch) -> list[dict]:
    """build_research_agent without a model: create_agent's keyword arguments are recorded."""
    built: list[dict] = []
    monkeypatch.setattr(research, "build_llm", lambda *_args, **_kwargs: "no-llm")
    monkeypatch.setattr(research, "create_agent", lambda **kwargs: built.append(kwargs) or kwargs)
    return built


def test_only_the_live_collection_gets_the_ingest_tool(settings, monkeypatch, fake_index, captured_agents):
    monkeypatch.setattr(research, "open_live_collection", lambda _settings: fake_index)

    research.build_research_agent(settings, fake_index)
    research.build_research_agent(settings, research.LiveCollection(settings))

    plain, live = ({tool.name for tool in kwargs["tools"]} for kwargs in captured_agents)
    assert "ingest_new_papers" not in plain
    assert live == plain | {"ingest_new_papers"}
    assert captured_agents[1]["system_prompt"] == captured_agents[0]["system_prompt"] + research.LIVE_PROMPT


def test_ingest_tool_runs_the_collection_ingest_and_returns_its_summary(settings, monkeypatch, fake_index, captured_agents):
    calls = []

    def fake_ingest_topic(_settings, topic, *, published_since=None):
        calls.append((topic, published_since))
        return IngestResult(topic=topic, published_since=published_since or "default", blocked_reason="a test block"), None

    monkeypatch.setattr(research, "open_live_collection", lambda _settings: fake_index)
    monkeypatch.setattr(research, "ingest_topic", fake_ingest_topic)
    live = research.LiveCollection(settings)
    agent_kwargs = research.build_research_agent(settings, live)
    ingest_tool = next(tool for tool in agent_kwargs["tools"] if tool.name == "ingest_new_papers")

    first = ingest_tool.invoke({"topic": TOPIC})
    ingest_tool.invoke({"topic": TOPIC, "published_since": "2025-01-01"})

    assert calls == [(TOPIC, None), (TOPIC, "2025-01-01")], "an empty published_since means the default window"
    assert first.startswith("BLOCKED.") and "a test block" in first
    assert len(live.ingest_results) == 2 and live._index is fake_index, "a blocked ingest keeps the current index"


@pytest.mark.slow
def test_live_collection_serves_the_new_index_after_an_ingest(settings, crossref):
    live = research.load_index(settings, "live")
    assert isinstance(live, research.LiveCollection)
    assert live.collection.count() == SNAPSHOT_PAPERS and live.lookup("10.9999/vla.1") is None

    crossref.payload = _payload(*_vla_papers(5))
    result = live.ingest(TOPIC)

    assert result.indexed is True and result.new_papers == 5
    assert live.ingest_results == [result]
    assert live.lookup("10.9999/vla.1")["paper_id"] == "10.9999/vla.1"
    assert live.search(VLA_QUERY, top_k=1)[0].paper_id in NEW_DOIS
    assert live.collection.count() == 29

    live.reset()
    assert live.ingest_results == []
    assert live.lookup("10.9999/vla.1") is None and live.collection.count() == SNAPSHOT_PAPERS


@pytest.mark.slow
def test_live_collection_keeps_its_index_when_an_ingest_is_blocked(settings, crossref):
    live = research.LiveCollection(settings)
    before = live._index
    crossref.error = requests.ConnectionError("down")

    result = live.ingest(TOPIC)

    assert result.indexed is False and live.ingest_results == [result]
    assert live._index is before and live.collection.count() == SNAPSHOT_PAPERS


class ScriptedAgent:
    """Stands in for the LangChain agent: runs the ingest itself, as the tool would, then returns
    the messages a ReAct loop leaves behind (ingest, search, answer)."""

    def __init__(self, live):
        self.live = live

    def invoke(self, payload: dict) -> dict:
        summary = self.live.ingest(TOPIC).summary()
        [hit] = self.live.search(VLA_QUERY, top_k=1)
        return {
            "messages": [
                HumanMessage(content=payload["messages"][0]["content"]),
                AIMessage(content="", tool_calls=[{"name": "ingest_new_papers", "args": {"topic": TOPIC}, "id": "call-1"}]),
                ToolMessage(content=summary, tool_call_id="call-1", name="ingest_new_papers"),
                AIMessage(content="", tool_calls=[{"name": "semantic_search_papers", "args": {"top_k": 1, "query": "vla grasping"}, "id": "call-2"}]),
                ToolMessage(
                    content=f"paper_id: {hit.paper_id}\ntitle: {hit.title}\nscore: {hit.score:.4f}\n{hit.content}",
                    tool_call_id="call-2",
                    name="semantic_search_papers",
                ),
                AIMessage(content=f"Five papers were added; the closest is [{hit.paper_id}]."),
            ]
        }


@pytest.mark.slow
def test_ask_agent_reports_only_the_ingest_this_question_ran(settings, crossref):
    live = research.load_index(settings, "live")
    crossref.error = requests.ConnectionError("down")
    live.ingest(TOPIC)  # an earlier, blocked ingest: it must not be reported again
    crossref.error = None
    crossref.payload = _payload(*_vla_papers(5))

    answer = research.ask_agent(ScriptedAgent(live), live, "Update the collection with VLA robot papers")

    [ingest] = answer.ingests
    assert ingest is live.ingest_results[-1] and len(live.ingest_results) == 2
    assert ingest.indexed is True and ingest.new_papers == 5
    assert answer.mode == "agent" and answer.answer.startswith("Five papers were added")
    assert answer.tool_calls == ["ingest_new_papers(vla robots)", "semantic_search_papers(vla grasping)"]
    [source] = answer.sources
    assert source["paper_id"] in NEW_DOIS, "the source is looked up through the swapped-in index"
