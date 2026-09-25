"""The research assistant behind the chat: a tool-using agent over one ChromaDB collection.

The agent is a ReAct loop (LangChain create_agent): it picks a tool, reads what came back and
decides whether to call another before answering. Besides the two tools of `retrieval/agent.py`
(semantic search and exact lookup) it can filter by author and by publication date, because
names and dates are exactly what embedding similarity is bad at. The prompt makes it cite DOIs,
and every step it took is returned so the page can show its reasoning path. The sources panel shows the papers the agent's tool
calls actually returned, parsed from the tool messages, not a second search run for display.

The Live collection's agent has a third tool, ingest_new_papers, which runs a topic through
the real pipeline (Crossref, cleaning, the quality gate, embedding) and grows that collection.

When the LLM is unavailable (no key, quota spent, provider error) the answer falls back to the
extractive `retrieval/qa.py` path and says so. A provider error is never shown as the model
declining to answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import re
import threading
from typing import Any
import unicodedata

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage

from core.config import Settings, normalized_provider
from pipelines.live_ingest import IngestResult, ingest_topic, open_live_collection, reset_live_collection
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question

COLLECTION_FILES = {
    "repaired": ("Repaired", "repaired_embeddings_json"),
    "baseline": ("Baseline", "embeddings_json"),
    "corrupted": ("Corrupted", "corrupted_embeddings_json"),
    "live": ("Live", None),
}

SYSTEM_PROMPT = (
    "You are a research assistant for a small corpus of scholarly papers indexed from Crossref. "
    "Work step by step: pick the tool that fits, read what it returns, and call another tool if that is not enough. "
    "Use find_papers_by_author for who-wrote-what questions, find_papers_by_date for questions about when or about a "
    "period (pass topic too when the user names one), semantic_search_papers for topics, and lookup_paper when the user "
    "names a paper. Never answer without at least one tool call. Answer only from what the tools return. After every "
    "claim, cite the paper's DOI in square brackets, for example [10.1145/3637528.3671801]. If the tools return nothing "
    "relevant, say the corpus does not cover it. Reply in the language the user wrote in, in at most two short paragraphs."
)

LIVE_PROMPT = (
    " This collection can grow. When the user asks to update, refresh, fetch or add papers about a topic, "
    "first call ingest_new_papers with a short English search query for that topic; pass published_since "
    "(YYYY-MM-DD) only if the user names a start date. Then say in one sentence what the quality gate decided, "
    "using the tool's numbers exactly, then call semantic_search_papers and answer from the collection. "
    "If ingestion was blocked, say so and give the reason; never claim papers were added when they were not. "
    "Do not call ingest_new_papers for ordinary questions."
)

PAPER_BLOCK = re.compile(r"paper_id:\s*(\S+)\s*\ntitle:[^\n]*(?:\nscore:\s*([0-9.]+))?")


@dataclass
class ResearchAnswer:
    question: str
    answer: str
    mode: str  # "agent" or "extractive"
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    error: str | None = None
    ingests: list[IngestResult] = field(default_factory=list)
    # The ReAct path, one entry per tool call: {"tool", "argument", "observation", "thought"}.
    steps: list[dict[str, str]] = field(default_factory=list)


class LiveCollection:
    """A stable handle on the Live collection. The agent's tools hold this object, so an ingest
    swaps the index underneath them without rebuilding the agent. Reads (search, lookup,
    documents) go to whichever index is current."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ingest_results: list[IngestResult] = []
        self._lock = threading.Lock()
        self._index = open_live_collection(settings)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["_index"], name)

    def ingest(self, topic: str, published_since: str | None = None) -> IngestResult:
        with self._lock:
            result, index = ingest_topic(self.settings, topic, published_since=published_since)
            if index is not None:
                self._index = index
            self.ingest_results.append(result)
            return result

    def reset(self) -> None:
        with self._lock:
            self._index = reset_live_collection(self.settings)
            self.ingest_results.clear()


def load_index(settings: Settings, state: str) -> LocalEmbeddingIndex | LiveCollection:
    if state == "live":
        return LiveCollection(settings)
    manifest = getattr(settings.paths, COLLECTION_FILES[state][1])
    return LocalEmbeddingIndex.load(settings, manifest)


def llm_available(settings: Settings) -> tuple[bool, str]:
    provider = normalized_provider(settings)
    if provider == "mock":
        return False, "LLM_PROVIDER=mock"
    if provider == "gemini" and not settings.google_api_key:
        return False, "GOOGLE_API_KEY chưa có trong .env"
    return True, f"{settings.llm_provider} / {settings.model_name}"


def _fold(text: str) -> str:
    """Lowercase without accents, so "Nguyen" finds "Nguyễn"."""
    # Đ has no Unicode decomposition, so NFKD alone would leave "Đoàn" unreachable from "Doan".
    text = (text or "").replace("Đ", "D").replace("đ", "d")
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()


def _day_bound(value: str, *, upper: bool) -> date | None:
    """YYYY, YYYY-MM or YYYY-MM-DD as the first (or, with upper, the last) day it covers; anything else is no bound."""
    value = (value or "").strip()
    try:
        if re.fullmatch(r"\d{4}", value):
            return date(int(value), 12, 31) if upper else date(int(value), 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = map(int, value.split("-"))
            first = date(year, month, 1)
            return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1) if upper else first
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
    except ValueError:
        return None
    return None


def _paper_block(document: dict[str, Any], score: float | None = None) -> str:
    metadata = document["metadata"]
    scored = f"\nscore: {score:.4f}" if score is not None else ""
    return (
        f"paper_id: {document['paper_id']}\ntitle: {metadata['title']}{scored}\n"
        f"published: {metadata['published']}\nauthors: {metadata['authors_joined']}\n"
        f"summary: {(metadata['summary'] or '')[:500]}"
    )


def build_research_agent(settings: Settings, index: LocalEmbeddingIndex | LiveCollection):
    @tool
    def semantic_search_papers(query: str, top_k: int = 4) -> str:
        """Search the paper corpus by meaning and return the most relevant papers."""
        return "\n\n".join(
            f"paper_id: {result.paper_id}\ntitle: {result.title}\nscore: {result.score:.4f}\n{result.content}"
            for result in index.search(query, top_k=top_k)
        )

    @tool
    def lookup_paper(paper_id_or_title: str) -> str:
        """Look up one paper by its exact DOI or exact title."""
        record = index.lookup(paper_id_or_title)
        if not record:
            return "No exact paper match found."
        return f"paper_id: {record['paper_id']}\ntitle: {record['title']}\n{record['content']}"

    @tool
    def find_papers_by_author(author: str) -> str:
        """Find papers with this author. Matching ignores case and accents; a surname alone works."""
        wanted = " ".join(_fold(author).split())
        # Whole words only: "Do" is Bao Do, not Thuy Doan.
        pattern = re.compile(rf"(?<!\w){re.escape(wanted)}(?!\w)") if wanted else None
        matches = [document for document in index.documents if pattern and pattern.search(_fold(document["metadata"]["authors_joined"]))]
        matches.sort(key=lambda document: document["metadata"]["published"], reverse=True)
        if not matches:
            return f"No paper in the collection has an author matching '{author}'."
        return f"{len(matches)} paper(s) by '{author}', newest first:\n\n" + "\n\n".join(_paper_block(document) for document in matches[:8])

    @tool
    def find_papers_by_date(published_after: str = "", published_before: str = "", topic: str = "") -> str:
        """List papers published in a date range, inclusive. Dates are YYYY, YYYY-MM or YYYY-MM-DD; leave one
        empty for an open range. With topic, papers in the range are ranked by relevance to it, else newest first."""
        after, before = _day_bound(published_after, upper=False), _day_bound(published_before, upper=True)

        def in_range(document: dict[str, Any]) -> bool:
            published = date.fromisoformat(document["metadata"]["published"])
            return (after is None or published >= after) and (before is None or published <= before)

        if topic.strip():
            ranked = [(index.lookup(result.paper_id), result.score) for result in index.search(topic, top_k=len(index.documents))]
            in_window = [(document, score) for document, score in ranked if document and in_range(document)]
            order = "most relevant"
        else:
            newest = sorted((document for document in index.documents if in_range(document)), key=lambda document: document["metadata"]["published"], reverse=True)
            in_window = [(document, None) for document in newest]
            order = "newest"
        window = f"{after or 'the beginning'} to {before or 'today'}"
        if not in_window:
            return f"No paper in the collection was published from {window}."
        hits = in_window[:8]
        # The count is the whole window, so the agent never mistakes "8 shown" for "8 exist".
        shown = f", showing the {len(hits)} {order}" if len(hits) < len(in_window) else ""
        return f"{len(in_window)} paper(s) published from {window}{shown}:\n\n" + "\n\n".join(_paper_block(document, score) for document, score in hits)

    tools = [semantic_search_papers, lookup_paper, find_papers_by_author, find_papers_by_date]
    prompt = SYSTEM_PROMPT
    if isinstance(index, LiveCollection):

        @tool
        def ingest_new_papers(topic: str, published_since: str = "") -> str:
            """Fetch recent papers on a topic from Crossref, run them through the data-quality gate, and add
            the ones that pass to this collection. topic: a short English search query. published_since:
            optional YYYY-MM-DD; leave empty for the last 180 days."""
            return index.ingest(topic, published_since or None).summary()

        tools.append(ingest_new_papers)
        prompt += LIVE_PROMPT

    return create_agent(
        model=build_llm(settings, temperature=0.0),
        tools=tools,
        system_prompt=prompt,
        name="paper_research_agent",
    )


def _text_of(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):  # Gemini 3 returns a list of typed parts
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content).strip()
    return str(content).strip()


def _source(index: LocalEmbeddingIndex, paper_id: str, score: float | None, via: str = "cosine") -> dict[str, Any] | None:
    document = index.lookup(paper_id)
    if not document:
        return None
    metadata = document["metadata"]
    return {
        "paper_id": document["paper_id"],
        "title": metadata["title"],
        "authors_joined": metadata["authors_joined"],
        "published": metadata["published"],
        "summary": metadata["summary"],
        "abs_url": metadata["abs_url"],
        "score": score,
        "via": "cosine" if score is not None else via,
    }


def _observation(tool_name: str, text: str) -> str:
    """One line on what a tool call returned, for the step trace."""
    if tool_name == "ingest_new_papers":
        return text.split(". ", 1)[0]
    papers = PAPER_BLOCK.findall(text)
    if not papers:
        return text.split("\n", 1)[0][:90]
    scores = [float(score) for _, score in papers if score]
    best = f", cosine cao nhất {max(scores):.3f}" if scores else ""
    return f"{len(papers)} bài{best}"


def ask_agent(agent: Any, index: LocalEmbeddingIndex | LiveCollection, question: str) -> ResearchAnswer:
    ingests_before = len(getattr(index, "ingest_results", []))
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    messages = result.get("messages", [])
    tool_calls: list[str] = []
    steps: list[dict[str, str]] = []
    step_by_call: dict[str, dict[str, str]] = {}
    seen: dict[str, tuple[float | None, str]] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            # Text the model wrote alongside its tool calls is its stated reasoning for that step.
            thought = _text_of(message) if message.tool_calls else ""
            for call in message.tool_calls or []:
                args = call.get("args", {})
                # Show what was searched for, not top_k, whichever order the model put them in.
                if call["name"] == "find_papers_by_date":
                    names = {"published_after": "sau", "published_before": "trước", "topic": "chủ đề"}
                    argument = ", ".join(f"{names.get(key, key)} {value}" for key, value in args.items() if value)
                else:
                    argument = args.get("query") or args.get("paper_id_or_title") or args.get("topic") or args.get("author")
                    if argument is None:
                        argument = ", ".join(f"{key}={value}" for key, value in args.items() if value)
                tool_calls.append(f"{call['name']}({str(argument)[:60]})")
                step = {"tool": call["name"], "argument": str(argument)[:80], "observation": "", "thought": thought}
                thought = ""
                steps.append(step)
                step_by_call[call.get("id") or str(len(steps))] = step
        elif isinstance(message, ToolMessage):
            text = _text_of(message)
            if (step := step_by_call.get(message.tool_call_id)) is not None:
                step["observation"] = _observation(step["tool"], text)
            via = "exact" if getattr(message, "name", "") == "lookup_paper" else "filter"
            for paper_id, score in PAPER_BLOCK.findall(text):
                if paper_id not in seen or (seen[paper_id][0] is None and score):
                    seen[paper_id] = (float(score), "cosine") if score else (None, via)
    # Text written alongside a tool call is a step's reasoning, never the answer.
    final = next(
        (text for message in reversed(messages) if isinstance(message, AIMessage) and not message.tool_calls and (text := _text_of(message))),
        "",
    )
    sources = [source for paper_id, (score, via) in seen.items() if (source := _source(index, paper_id, score, via))]
    ingests = list(getattr(index, "ingest_results", [])[ingests_before:])
    return ResearchAnswer(
        question=question, answer=final, mode="agent", sources=sources, tool_calls=tool_calls, ingests=ingests, steps=steps
    )


def ask_extractive(settings: Settings, index: LocalEmbeddingIndex, question: str, error: str | None = None) -> ResearchAnswer:
    """No LLM: nearest papers by embedding, answer lifted from the top paper's fields."""
    result = answer_question(question, settings=settings, index=index)
    scores = {item.paper_id: item.score for item in index.search(question)}
    sources = [source for paper_id in result.retrieved_doc_ids if (source := _source(index, paper_id, scores.get(paper_id)))]
    top = f" [{sources[0]['paper_id']}]" if sources else ""
    return ResearchAnswer(question=question, answer=result.answer + top, mode="extractive", sources=sources, error=error)
