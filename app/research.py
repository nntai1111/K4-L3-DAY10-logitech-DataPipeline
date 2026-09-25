"""The research assistant behind the chat: a tool-using agent over one ChromaDB collection.

The agent gets the same two tools as `retrieval/agent.py` (semantic search and exact lookup)
and a prompt that makes it cite DOIs. The sources panel shows the papers the agent's tool
calls actually returned, parsed from the tool messages, not a second search run for display.

When the LLM is unavailable (no key, quota spent, provider error) the answer falls back to the
extractive `retrieval/qa.py` path and says so. A provider error is never shown as the model
declining to answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage

from core.config import Settings, normalized_provider
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question

COLLECTION_FILES = {
    "repaired": ("Repaired", "repaired_embeddings_json"),
    "baseline": ("Baseline", "embeddings_json"),
    "corrupted": ("Corrupted", "corrupted_embeddings_json"),
}

SYSTEM_PROMPT = (
    "You are a research assistant for a small corpus of scholarly papers indexed from Crossref. "
    "Always call semantic_search_papers before answering, and lookup_paper when the user names a paper. "
    "Answer only from what the tools return. After every claim, cite the paper's DOI in square brackets, "
    "for example [10.1145/3637528.3671801]. If the tools return nothing relevant, say the corpus does not "
    "cover it. Reply in the language the user wrote in, in at most two short paragraphs."
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


def load_index(settings: Settings, state: str) -> LocalEmbeddingIndex:
    manifest = getattr(settings.paths, COLLECTION_FILES[state][1])
    return LocalEmbeddingIndex.load(settings, manifest)


def llm_available(settings: Settings) -> tuple[bool, str]:
    provider = normalized_provider(settings)
    if provider == "mock":
        return False, "LLM_PROVIDER=mock"
    if provider == "gemini" and not settings.google_api_key:
        return False, "GOOGLE_API_KEY chưa có trong .env"
    return True, f"{settings.llm_provider} / {settings.model_name}"


def build_research_agent(settings: Settings, index: LocalEmbeddingIndex):
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

    return create_agent(
        model=build_llm(settings, temperature=0.0),
        tools=[semantic_search_papers, lookup_paper],
        system_prompt=SYSTEM_PROMPT,
        name="paper_research_agent",
    )


def _text_of(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):  # Gemini 3 returns a list of typed parts
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content).strip()
    return str(content).strip()


def _source(index: LocalEmbeddingIndex, paper_id: str, score: float | None) -> dict[str, Any] | None:
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
    }


def ask_agent(agent: Any, index: LocalEmbeddingIndex, question: str) -> ResearchAnswer:
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    messages = result.get("messages", [])
    tool_calls: list[str] = []
    seen: dict[str, float | None] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                argument = next(iter(call.get("args", {}).values()), "")
                tool_calls.append(f"{call['name']}({str(argument)[:60]})")
        elif isinstance(message, ToolMessage):
            for paper_id, score in PAPER_BLOCK.findall(_text_of(message)):
                if paper_id not in seen or (seen[paper_id] is None and score):
                    seen[paper_id] = float(score) if score else None
    final = next((_text_of(message) for message in reversed(messages) if isinstance(message, AIMessage) and _text_of(message)), "")
    sources = [source for paper_id, score in seen.items() if (source := _source(index, paper_id, score))]
    return ResearchAnswer(question=question, answer=final, mode="agent", sources=sources, tool_calls=tool_calls)


def ask_extractive(settings: Settings, index: LocalEmbeddingIndex, question: str, error: str | None = None) -> ResearchAnswer:
    """No LLM: nearest papers by embedding, answer lifted from the top paper's fields."""
    result = answer_question(question, settings=settings, index=index)
    scores = {item.paper_id: item.score for item in index.search(question)}
    sources = [source for paper_id in result.retrieved_doc_ids if (source := _source(index, paper_id, scores.get(paper_id)))]
    top = f" [{sources[0]['paper_id']}]" if sources else ""
    return ResearchAnswer(question=question, answer=result.answer + top, mode="extractive", sources=sources, error=error)
