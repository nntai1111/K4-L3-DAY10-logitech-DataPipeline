"""Add fresh papers on a topic, on request, through the same pipeline and quality gate.

    Crossref (live) -> parse -> clean -> quarantine bad rows -> gate on the new batch -> merge
    -> gate on the merged table -> embed into the `papers-live` collection

The Live collection starts as a copy of the clean snapshot and grows each time the research
agent is asked for new papers. Data from the wild is messier than the snapshot, so rows that
break a row-level rule (empty id or title, short summary, truncated title, a run of junk
symbols such as leaked LaTeX) are quarantined with their reason instead of sinking the whole
batch. What remains must still pass the full Great Expectations suite and the freshness SLA,
and so must the merged table; if either gate fails, nothing is indexed and the collection
stays exactly as it was.

Everything here writes under `data/live/` (raw responses, quality reports, its own ChromaDB
directory, an ingest log), which is gitignored. The official artifacts under `data/raw`,
`data/clean`, `data/quality` and `data/chroma` are never touched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
import logging
import re
import time

import pandas as pd

from core.config import Settings
from core.utils import now_utc, read_json, safe_slug, write_json
from ingestion.cleaning import CLEAN_COLUMNS, build_clean_dataframe
from ingestion.crossref import _fetch_live_payload, load_raw_records, parse_crossref_payload
from observability.quality import JUNK_SYMBOL_RUN, MIN_SUMMARY_CHARS, MIN_TITLE_CHARS, run_data_quality_checks
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)

LIVE_COLLECTION = "papers-live"
LIVE_BATCH_SIZE = 20
ISO_DAY = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


@dataclass
class IngestResult:
    """One ingest run, stage by stage, for the agent's reply and the UI card."""

    topic: str
    published_since: str
    fetched: int = 0
    batch_rows: int = 0
    quarantined: list[dict[str, str]] = field(default_factory=list)
    batch_gate_passed: bool | None = None
    batch_failed: list[str] = field(default_factory=list)
    batch_stale_ratio: float | None = None
    already_indexed: int = 0
    new_papers: int = 0
    merged_gate_passed: bool | None = None
    merged_failed: list[str] = field(default_factory=list)
    total_papers: int = 0
    indexed: bool = False
    blocked_reason: str | None = None
    added: list[dict[str, str]] = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> str:
        """What the agent is told, in words it can repeat without inventing numbers."""
        held = (
            f" {len(self.quarantined)} were quarantined by row checks ("
            + "; ".join(f"{row['paper_id']}: {row['reason']}" for row in self.quarantined[:5])
            + ")."
            if self.quarantined else ""
        )
        if not self.indexed:
            return (
                f"BLOCKED. Ingestion for '{self.topic}' (published since {self.published_since}) was stopped: "
                f"{self.blocked_reason}. Crossref returned {self.fetched} items, {self.batch_rows} survived cleaning.{held} "
                "Nothing was indexed; the collection is unchanged."
            )
        if not self.new_papers:
            return (
                f"PASSED, nothing new. Crossref returned {self.fetched} items on '{self.topic}', the batch passed the "
                f"quality gate, but all {self.already_indexed} were already in the collection ({self.total_papers} papers).{held}"
            )
        listing = "\n".join(f"- {paper['paper_id']} | {paper['published']} | {paper['title']}" for paper in self.added[:10])
        return (
            f"PASSED and indexed. Crossref returned {self.fetched} items on '{self.topic}' (published since "
            f"{self.published_since}); {self.batch_rows} survived cleaning.{held} The rest passed the quality gate; "
            f"{self.new_papers} were new ({self.already_indexed} already in the collection). "
            f"The collection now holds {self.total_papers} papers. New papers (DOI | published | title):\n{listing}"
        )


def live_dir(settings: Settings) -> Path:
    return settings.paths.project_dir / "data" / "live"


def live_settings(settings: Settings) -> Settings:
    """The same settings with every write the pipeline makes redirected under data/live/."""
    root = live_dir(settings)
    return replace(settings, paths=replace(settings.paths, quality_dir=root / "quality", chroma_dir=root / "chroma"))


def _manifest(settings: Settings) -> Path:
    return live_dir(settings) / f"{LIVE_COLLECTION}.json"


def _table_path(settings: Settings) -> Path:
    return live_dir(settings) / "papers_live_clean.json"


def _with_current_ages(table: pd.DataFrame, run_day: date) -> pd.DataFrame:
    """age_days was computed on the day each paper was added; the gate needs it as of today."""
    table = table.copy()
    table["age_days"] = [(run_day - date.fromisoformat(published)).days for published in table["published"]]
    return table


def _snapshot_table(settings: Settings, run_day: date) -> pd.DataFrame:
    return build_clean_dataframe(load_raw_records(settings.paths.raw_records_json), run_day)


def _index(settings: Settings, table: pd.DataFrame) -> LocalEmbeddingIndex:
    index = LocalEmbeddingIndex.build(table, live_settings(settings), _manifest(settings))
    write_json(_table_path(settings), table.to_dict(orient="records"))
    return index


def open_live_collection(settings: Settings) -> LocalEmbeddingIndex:
    """The Live collection, seeded from the clean snapshot the first time it is opened."""
    if _manifest(settings).exists() and _table_path(settings).exists():
        return LocalEmbeddingIndex.load(live_settings(settings), _manifest(settings))
    return _index(settings, _snapshot_table(settings, now_utc().date()))


def reset_live_collection(settings: Settings) -> LocalEmbeddingIndex:
    """Back to the snapshot: drop everything ingested, keep the raw responses and the log."""
    return _index(settings, _snapshot_table(settings, now_utc().date()))


def live_paper_count(settings: Settings) -> int | None:
    path = _table_path(settings)
    return len(read_json(path)) if path.exists() else None


def ingest_history(settings: Settings, limit: int | None = None) -> list[dict]:
    """Every logged ingest run, newest first."""
    logs = sorted((live_dir(settings) / "ingest_log").glob("*.json"), reverse=True)[:limit]
    return [read_json(path) for path in logs]


# Plain-language buckets for why a run was blocked or a row was held back, checked in order.
BLOCK_BUCKETS = (
    ("Crossref could not be reached", "Không gọi được Crossref"),
    ("parser does not understand", "Phản hồi Crossref lạ"),
    ("no usable papers", "Crossref không có bài phù hợp"),
    ("was quarantined by the row checks", "Cả lô bị cách ly"),
    ("merged collection would fail", "Kho gộp không qua gate"),
    ("freshness SLA", "Freshness SLA (dữ liệu cũ)"),
    ("expect_table_row_count", "Quá ít bài"),
)
QUARANTINE_BUCKETS = (
    ("junk symbols", "Ký tự rác trong tóm tắt"),
    ("summary under", "Tóm tắt quá ngắn"),
    ("title under", "Tiêu đề quá ngắn"),
    ("missing", "Thiếu id, tiêu đề hoặc nội dung"),
)


def _bucket(text: str, buckets: tuple[tuple[str, str], ...]) -> str:
    return next((label for needle, label in buckets if needle in text), "Khác")


def gate_stats(history: list[dict]) -> dict:
    """What the gate did across all live ingests: runs, verdicts, rows in and out, and why."""
    blocked = [run for run in history if not run.get("indexed")]
    fetched = sum(run.get("fetched", 0) for run in history)
    quarantined = [row for run in history for row in run.get("quarantined") or []]
    block_reasons: dict[str, int] = {}
    for run in blocked:
        label = _bucket(run.get("blocked_reason") or "", BLOCK_BUCKETS)
        block_reasons[label] = block_reasons.get(label, 0) + 1
    quarantine_reasons: dict[str, int] = {}
    for row in quarantined:
        label = _bucket(row.get("reason") or "", QUARANTINE_BUCKETS)
        quarantine_reasons[label] = quarantine_reasons.get(label, 0) + 1
    return {
        "runs": len(history),
        "passed": len(history) - len(blocked),
        "blocked": len(blocked),
        "fetched": fetched,
        "quarantined": len(quarantined),
        "added": sum(run.get("new_papers", 0) for run in history if run.get("indexed")),
        "pass_rate": (len(history) - len(blocked)) / len(history) if history else None,
        "block_reasons": dict(sorted(block_reasons.items(), key=lambda item: -item[1])),
        "quarantine_reasons": dict(sorted(quarantine_reasons.items(), key=lambda item: -item[1])),
    }


def quarantine_reason(row: dict) -> str | None:
    """The row-level rules of the quality suite, applied one row at a time. Thresholds come from
    observability.quality, so this and the GX suite cannot drift apart."""
    if not row["paper_id"] or not row["title"] or not row["text_for_embedding"]:
        return "missing paper_id, title or text"
    if len(row["summary"] or "") < MIN_SUMMARY_CHARS:
        return f"summary under {MIN_SUMMARY_CHARS} characters"
    if len(row["title"]) < MIN_TITLE_CHARS:
        return f"title under {MIN_TITLE_CHARS} characters"
    match = re.search(JUNK_SYMBOL_RUN, row["summary"])
    if match:
        return f"junk symbols in summary ({match.group(0)})"
    return None


def _crossref_filter(published_since: str) -> str:
    return f"from-pub-date:{published_since},has-abstract:true"


def _valid_since(value: str | None) -> str | None:
    """YYYY, YYYY-MM or YYYY-MM-DD naming a real date, else None (Crossref rejects 2025-02-30)."""
    value = (value or "").strip()
    if not ISO_DAY.match(value):
        return None
    parts = [int(part) for part in value.split("-")]
    try:
        date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError:
        return None
    return value


def _unique(path: Path) -> Path:
    """Two runs in the same second must not overwrite each other's log."""
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{number}{path.suffix}")
        number += 1
    return candidate


def _default_since(settings: Settings) -> str:
    return settings.source_filter.split("from-pub-date:", 1)[1].split(",", 1)[0]


def ingest_topic(
    settings: Settings,
    topic: str,
    *,
    published_since: str | None = None,
    max_results: int = LIVE_BATCH_SIZE,
) -> tuple[IngestResult, LocalEmbeddingIndex | None]:
    """Run one topic through the pipeline. Returns the result and the new index, or None when blocked."""
    started = time.time()
    since = _valid_since(published_since) or _default_since(settings)
    result = IngestResult(topic=topic.strip(), published_since=since)
    run_day = now_utc().date()
    stamp = now_utc().strftime("%Y%m%dT%H%M%S")
    live = live_settings(settings)

    def finish(index: LocalEmbeddingIndex | None) -> tuple[IngestResult, LocalEmbeddingIndex | None]:
        result.seconds = round(time.time() - started, 2)
        write_json(_unique(live_dir(settings) / "ingest_log" / f"{stamp}-{safe_slug(topic)[:48]}.json"), asdict(result) | {"at": stamp})
        return result, index

    # 1. Fetch. A live failure blocks the run; it never falls back to the snapshot, because
    #    "no new data" must not look like "the update succeeded".
    query = replace(settings, source_query=result.topic, source_filter=_crossref_filter(since), max_results=max_results)
    try:
        payload = _fetch_live_payload(query)
    except Exception as error:  # network, 429 after retries, bad JSON
        logger.warning("Live ingest fetch failed: %s", error)
        result.blocked_reason = f"Crossref could not be reached ({type(error).__name__})"
        return finish(None)
    write_json(_unique(live_dir(settings) / "raw" / f"{stamp}-{safe_slug(topic)[:48]}.json"), payload)
    message = payload.get("message") if isinstance(payload, dict) else None
    items = message.get("items") if isinstance(message, dict) else None
    result.fetched = len(items) if isinstance(items, list) else 0
    try:
        records = parse_crossref_payload(payload) if result.fetched else []
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        logger.warning("Live ingest could not parse the Crossref response: %s", error)
        result.blocked_reason = f"Crossref returned a response the parser does not understand ({type(error).__name__})"
        return finish(None)

    # 2. Clean, quarantine the rows that break a row rule, then gate what is left on its own.
    batch = build_clean_dataframe(records, run_day)
    result.batch_rows = len(batch)
    if batch.empty:
        result.blocked_reason = "Crossref returned no usable papers for this topic and date range"
        return finish(None)
    reasons = [quarantine_reason(row) for row in batch.to_dict(orient="records")]
    result.quarantined = [
        {"paper_id": paper_id, "title": title, "reason": reason}
        for paper_id, title, reason in zip(batch["paper_id"], batch["title"], reasons)
        if reason
    ]
    batch = batch[[reason is None for reason in reasons]].reset_index(drop=True)
    if batch.empty:
        result.blocked_reason = f"every one of the {result.batch_rows} papers was quarantined by the row checks"
        return finish(None)
    batch_quality = run_data_quality_checks(batch, live, f"live-batch-{stamp}")
    result.batch_gate_passed = bool(batch_quality["gate_passed"])
    result.batch_failed = list(batch_quality["failed_expectations"])
    result.batch_stale_ratio = batch_quality["freshness"]["stale_ratio"]
    if not result.batch_gate_passed:
        reasons = list(result.batch_failed)
        if not batch_quality["freshness"]["is_fresh"]:
            reasons.append(f"freshness SLA ({result.batch_stale_ratio:.0%} of the batch is older than {settings.freshness_threshold_days} days, limit 25%)")
        result.blocked_reason = "the new batch failed " + "; ".join(reasons)
        return finish(None)

    # 3. Merge with what the collection already holds, then gate the table that would be served.
    table_path = _table_path(settings)
    current = pd.DataFrame(read_json(table_path)) if table_path.exists() else _snapshot_table(settings, run_day)
    current = _with_current_ages(current[CLEAN_COLUMNS], run_day)
    fresh = batch[~batch["paper_id"].isin(set(current["paper_id"]))]
    result.already_indexed = len(batch) - len(fresh)
    result.new_papers = len(fresh)
    merged = pd.concat([current, fresh], ignore_index=True)[CLEAN_COLUMNS]
    merged = merged.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    result.total_papers = len(merged)

    merged_quality = run_data_quality_checks(merged, live, f"live-merged-{stamp}")
    result.merged_gate_passed = bool(merged_quality["gate_passed"])
    result.merged_failed = list(merged_quality["failed_expectations"])
    if not result.merged_gate_passed:
        reasons = list(result.merged_failed) or ["freshness SLA"]
        result.blocked_reason = "the merged collection would fail " + "; ".join(reasons)
        result.total_papers = len(current)
        result.new_papers = 0  # nothing was added
        return finish(None)

    # 4. Index. Nothing new means nothing to rebuild.
    result.added = [
        {"paper_id": row["paper_id"], "title": row["title"], "published": row["published"]}
        for row in fresh.sort_values("published", ascending=False).to_dict(orient="records")
    ]
    result.indexed = True
    index = _index(settings, merged) if result.new_papers else None
    return finish(index)

