from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
import hashlib
import html
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

import requests

from core.config import Settings
from core.utils import ensure_parent, normalize_whitespace, now_utc, project_relative, read_json, write_json

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 30

# Crossref exposes several dates; the first one present wins.
PUBLISHED_DATE_FIELDS = ("published", "published-online", "published-print", "issued", "created")
UPDATED_DATE_FIELDS = ("deposited", "created")

_BLOCK_TAG_RE = re.compile(r"</?jats:(p|title|sec|list|list-item|label|caption)\b[^>]*>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_ABSTRACT_HEADING_RE = re.compile(r"<jats:title>\s*(abstract|summary)\s*[:.]?\s*</jats:title>", re.IGNORECASE)
_LEADING_ABSTRACT_RE = re.compile(r"^(abstract|summary)\s*[:.\-]\s*", re.IGNORECASE)
_DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def ingestion_manifest_path(settings: Settings) -> Path:
    return settings.paths.raw_api_response.parent / "ingestion_manifest.json"


def _clean_markup(value: Any) -> str:
    """Strip JATS/HTML markup, decode entities and collapse whitespace."""
    text = _ABSTRACT_HEADING_RE.sub(" ", str(value or ""))
    text = _BLOCK_TAG_RE.sub(" ", text)
    text = _ANY_TAG_RE.sub("", text)
    return normalize_whitespace(html.unescape(text))


def _normalize_doi(value: Any) -> str:
    return _DOI_PREFIX_RE.sub("", str(value or "").strip()).lower()


def _unique_texts(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    texts: list[str] = []
    for value in values or []:
        text = _clean_markup(value)
        if text and text not in texts:
            texts.append(text)
    return texts


def _first_text(value: Any) -> str:
    texts = _unique_texts(value)
    return texts[0] if texts else ""


def _parse_authors(raw_authors: Any) -> list[str]:
    names: list[str] = []
    for author in raw_authors or []:
        if not isinstance(author, dict):
            continue
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        name = _clean_markup(name or author.get("name", ""))
        if name and name not in names:
            names.append(name)
    return names


def _parse_categories(item: dict[str, Any]) -> list[str]:
    categories = _unique_texts(item.get("subject"))
    if not categories and item.get("type"):
        categories = [str(item["type"]).replace("-", " ").title()]
    return categories or ["Uncategorized"]


def _date_from_block(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    parts = (block.get("date-parts") or [[]])[0] or []
    if parts and parts[0] is not None:
        year, month, day = (list(parts) + [1, 1])[:3]
        try:
            return date(int(year), int(month or 1), int(day or 1)).isoformat()
        except (TypeError, ValueError):
            return None
    date_time = block.get("date-time")
    return str(date_time)[:10] if date_time else None


def _first_date(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _date_from_block(item.get(key))
        if value:
            return value
    return ""


def _pdf_url(item: dict[str, Any], fallback: str) -> str:
    for link in item.get("link") or []:
        if isinstance(link, dict) and "pdf" in str(link.get("content-type", "")).lower() and link.get("URL"):
            return str(link["URL"])
    return fallback


def _parse_item(item: dict[str, Any]) -> PaperRecord | None:
    doi = _normalize_doi(item.get("DOI"))
    title = _first_text(item.get("title"))
    summary = _LEADING_ABSTRACT_RE.sub("", _clean_markup(item.get("abstract")))
    published = _first_date(item, PUBLISHED_DATE_FIELDS)
    if not doi or not title or not summary or not published:
        return None

    categories = _parse_categories(item)
    abs_url = str(item.get("URL") or f"https://doi.org/{doi}")
    return PaperRecord(
        paper_id=doi,
        title=title,
        summary=summary,
        authors=_parse_authors(item.get("author")),
        categories=categories,
        primary_category=categories[0],
        published=published,
        updated=_first_date(item, UPDATED_DATE_FIELDS) or published,
        abs_url=abs_url,
        pdf_url=_pdf_url(item, abs_url),
        comment=f"Crossref record {doi}",
    )


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse a Crossref `/works` payload into records, skipping items without DOI, title, abstract or date."""
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict):
        raise ValueError("Unexpected Crossref payload: missing `message` object.")
    if payload.get("status") not in (None, "ok"):
        raise ValueError(f"Crossref returned status={payload.get('status')!r}.")

    records: list[PaperRecord] = []
    for item in payload["message"].get("items") or []:
        if isinstance(item, dict):
            record = _parse_item(item)
            if record is not None:
                records.append(record)
    return records


def _request_crossref(settings: Settings) -> tuple[requests.Response, int]:
    """Call the Crossref API, retrying on 429/5xx and network errors with exponential backoff."""
    params: dict[str, Any] = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    headers = {"User-Agent": "day10-data-observability-lab/0.1 (python-requests)"}
    mailto = os.getenv("CROSSREF_MAILTO")
    if mailto:
        params["mailto"] = mailto

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after: str | None = None
        try:
            response = requests.get(CROSSREF_WORKS_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
        else:
            if response.status_code == 200:
                return response, attempt
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
            last_error = requests.HTTPError(f"HTTP {response.status_code} from Crossref", response=response)
            retry_after = response.headers.get("Retry-After")

        if attempt < MAX_ATTEMPTS:
            delay = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_SECONDS * 2 ** (attempt - 1)
            time.sleep(min(delay, MAX_BACKOFF_SECONDS))

    assert last_error is not None
    raise last_error


def _archive_previous_snapshot(path: Path, new_content: bytes) -> Path | None:
    """Keep the old raw snapshot instead of overwriting it silently (raw data is never destroyed)."""
    if not path.exists() or path.read_bytes() == new_content:
        return None
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    archive_path = path.parent / "archive" / f"{path.stem}_{stamp}{path.suffix}"
    ensure_parent(archive_path)
    shutil.copy2(path, archive_path)
    return archive_path


def _save_records(records: list[PaperRecord], path: Path) -> bool:
    """Write records only when their content changed, so reruns do not churn the raw artifact."""
    payload = [asdict(record) for record in records]
    if path.exists():
        try:
            if read_json(path) == payload:
                return False
        except (OSError, ValueError):
            pass
    write_json(path, payload)
    return True


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Load Crossref records and preserve raw lineage.

    Dev/offline mode (default): parse the committed snapshot `data/raw/crossref_response.json`.
    Live mode (`REFRESH_SOURCE=1`, or no snapshot yet): call the API with retry; on failure fall
    back to the snapshot. The raw response is stored byte-for-byte, the parsed records next to it.
    """
    paths = settings.paths
    root = paths.project_dir
    snapshot_available = paths.raw_api_response.exists()
    mode = "snapshot"
    attempts = 0
    fallback_reason: str | None = None
    archived: Path | None = None
    payload: dict | None = None

    if settings.refresh_source or not snapshot_available:
        try:
            response, attempts = _request_crossref(settings)
            payload = response.json()
            if not parse_crossref_payload(payload):
                raise ValueError("Crossref response contained no valid records.")
            archived = _archive_previous_snapshot(paths.raw_api_response, response.content)
            ensure_parent(paths.raw_api_response)
            paths.raw_api_response.write_bytes(response.content)
            mode = "live"
        except (requests.RequestException, ValueError) as exc:
            if not snapshot_available:
                raise RuntimeError(
                    f"Crossref API unavailable and no snapshot at {project_relative(paths.raw_api_response, root)}."
                ) from exc
            payload = None
            mode = "snapshot_fallback"
            fallback_reason = f"{type(exc).__name__}: {exc}"
            print(f"[crossref] Live API failed ({fallback_reason}); falling back to the local snapshot.")

    if payload is None:
        payload = read_json(paths.raw_api_response)

    records = parse_crossref_payload(payload)
    if not records:
        raise RuntimeError("Crossref payload produced no valid records.")
    records_rewritten = _save_records(records, paths.raw_records_json)

    raw_bytes = paths.raw_api_response.read_bytes()
    payload_items = len(payload["message"].get("items") or [])
    write_json(
        ingestion_manifest_path(settings),
        {
            "source_api": settings.source_api,
            "endpoint": CROSSREF_WORKS_URL,
            "query": settings.source_query,
            "filter": settings.source_filter,
            "rows": settings.max_results,
            "mode": mode,
            "attempts": attempts,
            "fallback_reason": fallback_reason,
            "loaded_at": now_utc().isoformat(),
            "raw_api_response": project_relative(paths.raw_api_response, root),
            "raw_api_response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "archived_previous_snapshot": project_relative(archived, root) if archived else None,
            "payload_items": payload_items,
            "valid_records": len(records),
            "skipped_items": payload_items - len(records),
            "raw_records_json": project_relative(paths.raw_records_json, root),
            "raw_records_rewritten": records_rewritten,
        },
    )
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Read a records snapshot (or a raw Crossref response) back into `PaperRecord` objects."""
    payload = read_json(Path(path))
    if isinstance(payload, dict) and "message" in payload:
        return parse_crossref_payload(payload)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list of records in {path}.")

    list_fields = {"authors", "categories"}
    records: list[PaperRecord] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        values: dict[str, Any] = {}
        for field in fields(PaperRecord):
            raw = row.get(field.name)
            if field.name in list_fields:
                values[field.name] = [str(item) for item in (raw or [])]
            else:
                values[field.name] = "" if raw is None else str(raw)
        if not values["primary_category"] and values["categories"]:
            values["primary_category"] = values["categories"][0]
        records.append(PaperRecord(**values))
    return records
