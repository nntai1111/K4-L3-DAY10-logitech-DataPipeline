from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import html
import logging
from pathlib import Path
import re
import time

import requests

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json

logger = logging.getLogger(__name__)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
USER_AGENT = "K4-L3-Day10-DataPipeline-Lab/0.1"
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:")
DATE_FIELDS_BY_PRIORITY = ("published", "published-print", "published-online", "issued", "created")
MARKUP_TAG = re.compile(r"<[^>]+>")


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


def strip_markup(text: str) -> str:
    """Remove JATS/HTML tags such as <jats:p> and decode entities like &amp;."""
    without_tags = MARKUP_TAG.sub(" ", text or "")
    return normalize_whitespace(html.unescape(without_tags))


def normalize_doi(raw_doi: str) -> str:
    doi = (raw_doi or "").strip()
    for prefix in DOI_PREFIXES:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip().lower()


def _iso_date_from_crossref(date_field: dict | None) -> str:
    """Crossref dates look like {"date-parts": [[2026, 5, 20]]}; month and day may be missing."""
    if not date_field:
        return ""
    parts = (date_field.get("date-parts") or [[]])[0]
    if parts and parts[0]:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        return f"{year:04d}-{month:02d}-{day:02d}"
    date_time = date_field.get("date-time") or ""
    return date_time[:10]


def _first_date(item: dict, field_names: tuple[str, ...]) -> str:
    for field_name in field_names:
        iso_date = _iso_date_from_crossref(item.get(field_name))
        if iso_date:
            return iso_date
    return ""


def _author_names(item: dict) -> list[str]:
    names = []
    for author in item.get("author") or []:
        full_name = author.get("name") or " ".join(part for part in (author.get("given"), author.get("family")) if part)
        full_name = normalize_whitespace(full_name)
        if full_name:
            names.append(full_name)
    return names


def _pdf_link(item: dict, fallback: str) -> str:
    for link in item.get("link") or []:
        if link.get("content-type") == "application/pdf" and link.get("URL"):
            return link["URL"]
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Turn a Crossref /works response into PaperRecords, skipping items without DOI, title or abstract."""
    records: list[PaperRecord] = []
    for item in payload.get("message", {}).get("items", []):
        paper_id = normalize_doi(item.get("DOI", ""))
        title = normalize_whitespace((item.get("title") or [""])[0])
        summary = strip_markup(item.get("abstract", ""))
        published = _first_date(item, DATE_FIELDS_BY_PRIORITY)
        if not (paper_id and title and summary and published):
            logger.warning("Skipping Crossref item without DOI, title, abstract or date: %s", item.get("DOI"))
            continue

        categories = [normalize_whitespace(subject) for subject in item.get("subject") or [] if normalize_whitespace(subject)]
        abs_url = item.get("URL") or f"https://doi.org/{paper_id}"
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=summary,
                authors=_author_names(item),
                categories=categories,
                primary_category=categories[0] if categories else "",
                published=published,
                updated=_first_date(item, ("updated", "deposited", "indexed")) or published,
                abs_url=abs_url,
                pdf_url=_pdf_link(item, fallback=abs_url),
                comment=f"Crossref record {paper_id}",
            )
        )
    return records


def _fetch_live_payload(settings: Settings) -> dict:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    headers = {"User-Agent": USER_AGENT}
    if settings.crossref_mailto:
        # Crossref routes requests that name a contact to its "polite pool", which has higher rate limits.
        params["mailto"] = settings.crossref_mailto
        headers["User-Agent"] = f"{USER_AGENT} (mailto:{settings.crossref_mailto})"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.get(CROSSREF_WORKS_URL, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        if response.status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS:
            response.raise_for_status()
        wait_seconds = float(response.headers.get("Retry-After", 2 ** attempt))
        logger.warning("Crossref returned %s, retrying in %.0fs (attempt %d)", response.status_code, wait_seconds, attempt)
        time.sleep(wait_seconds)
    raise RuntimeError("Crossref fetch exhausted its retries.")


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    records, _source_mode = fetch_source_records_with_mode(settings)
    return records


def fetch_source_records_with_mode(settings: Settings) -> tuple[list[PaperRecord], str]:
    """Load the paper records, from the live API when REFRESH_SOURCE=1 and from the committed snapshot otherwise.

    The snapshot at data/raw/crossref_response.json is the pipeline's source of truth, so a live fetch
    only overwrites it when it succeeds. Any live failure (429, 503, no network) falls back to it.
    """
    source_mode = "snapshot"
    payload = None
    if settings.refresh_source:
        try:
            payload = _fetch_live_payload(settings)
            write_json(settings.paths.raw_api_response, payload)
            source_mode = "live"
        except (requests.RequestException, RuntimeError, ValueError) as error:
            logger.warning("Live Crossref fetch failed (%s); falling back to the offline snapshot.", error)
    if payload is None:
        payload = read_json(settings.paths.raw_api_response)

    records = parse_crossref_payload(payload)
    write_json(settings.paths.raw_records_json, [asdict(record) for record in records])
    logger.info("Loaded %d records from %s", len(records), source_mode)
    return records, source_mode


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Read crossref_records.json back into PaperRecords, ignoring any unknown keys."""
    known_fields = {field.name for field in fields(PaperRecord)}
    return [PaperRecord(**{key: value for key, value in row.items() if key in known_fields}) for row in read_json(path)]
