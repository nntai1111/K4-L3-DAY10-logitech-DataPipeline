from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from core.config import Settings


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


def _clean_html_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    return " ".join(cleaned.split())


def _format_date(date_parts: list) -> str:
    if not date_parts or not isinstance(date_parts, list):
        return "2026-01-01"
    parts = date_parts[0] if isinstance(date_parts[0], list) else date_parts
    year = parts[0] if len(parts) > 0 else 2026
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse Crossref payload thanh list PaperRecord."""
    items = []
    if isinstance(payload, dict):
        message = payload.get("message", {})
        if isinstance(message, dict):
            items = message.get("items", [])
        elif isinstance(payload.get("items"), list):
            items = payload.get("items", [])
    elif isinstance(payload, list):
        items = payload

    records: list[PaperRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        paper_id = item.get("DOI") or item.get("paper_id") or ""
        if not paper_id:
            continue

        raw_title = item.get("title", "")
        if isinstance(raw_title, list):
            title = _clean_html_tags(" ".join(raw_title))
        else:
            title = _clean_html_tags(str(raw_title))

        if not title:
            continue

        raw_abstract = item.get("abstract") or item.get("summary") or ""
        summary = _clean_html_tags(str(raw_abstract))

        raw_authors = item.get("author") or item.get("authors") or []
        authors: list[str] = []
        if isinstance(raw_authors, list):
            for a in raw_authors:
                if isinstance(a, dict):
                    given = a.get("given", "").strip()
                    family = a.get("family", "").strip()
                    name = f"{given} {family}".strip()
                    if name:
                        authors.append(name)
                elif isinstance(a, str) and a.strip():
                    authors.append(a.strip())

        raw_subjects = item.get("subject") or item.get("categories") or []
        categories: list[str] = [str(s).strip() for s in raw_subjects if str(s).strip()]
        primary_category = categories[0] if categories else item.get("primary_category", "General")

        published_raw = item.get("published", {})
        if isinstance(published_raw, dict) and "date-parts" in published_raw:
            published = _format_date(published_raw.get("date-parts", []))
        elif isinstance(published_raw, str) and published_raw:
            published = published_raw[:10]
        else:
            published = item.get("published") or "2026-01-01"

        created_raw = item.get("created", {})
        if isinstance(created_raw, dict) and "date-time" in created_raw:
            updated = str(created_raw["date-time"])[:10]
        else:
            updated = item.get("updated") or published

        abs_url = item.get("URL") or item.get("abs_url") or f"https://doi.org/{paper_id}"
        pdf_url = item.get("pdf_url") or abs_url
        comment = item.get("comment") or f"Crossref record {paper_id}"

        records.append(
            PaperRecord(
                paper_id=str(paper_id),
                title=title,
                summary=summary,
                authors=authors,
                categories=categories,
                primary_category=str(primary_category),
                published=str(published),
                updated=str(updated),
                abs_url=str(abs_url),
                pdf_url=str(pdf_url),
                comment=str(comment),
            )
        )

    return records


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Goi source API (hoac local fallback), luu raw response, parse thanh records."""
    raw_api_path = settings.paths.raw_api_response
    raw_records_path = settings.paths.raw_records_json

    payload: dict | None = None

    if settings.refresh_source:
        try:
            params = {
                "query": settings.source_query,
                "filter": settings.source_filter,
                "rows": settings.max_results,
            }
            url = f"https://api.crossref.org/works?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "K4-L3-DataPipeline/1.0 (mailto:student@vinuni.edu.vn)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8")
                payload = json.loads(data)

            if payload:
                raw_api_path.parent.mkdir(parents=True, exist_ok=True)
                raw_api_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            payload = None

    if payload is None:
        if raw_api_path.exists():
            payload = json.loads(raw_api_path.read_text(encoding="utf-8"))
        elif raw_records_path.exists():
            return load_raw_records(raw_records_path)
        else:
            raise FileNotFoundError(f"Neither API response nor raw records snapshot found at {raw_api_path}")

    records = parse_crossref_payload(payload)

    raw_records_path.parent.mkdir(parents=True, exist_ok=True)
    dict_records = [asdict(r) for r in records]
    raw_records_path.write_text(json.dumps(dict_records, ensure_ascii=False, indent=2), encoding="utf-8")

    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Doc JSON snapshot va map thanh List[PaperRecord]."""
    if not path.exists():
        raise FileNotFoundError(f"Raw records file not found at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[PaperRecord] = []
    for item in data:
        records.append(
            PaperRecord(
                paper_id=item["paper_id"],
                title=item["title"],
                summary=item["summary"],
                authors=list(item.get("authors", [])),
                categories=list(item.get("categories", [])),
                primary_category=item.get("primary_category", "General"),
                published=item.get("published", ""),
                updated=item.get("updated", ""),
                abs_url=item.get("abs_url", ""),
                pdf_url=item.get("pdf_url", ""),
                comment=item.get("comment", ""),
            )
        )
    return records

