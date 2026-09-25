from __future__ import annotations

from dataclasses import asdict, replace
import json

import pytest
import requests

from core.utils import read_json
from ingestion import crossref
from ingestion.crossref import fetch_source_records, ingestion_manifest_path, load_raw_records, parse_crossref_payload


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        raise requests.HTTPError(f"HTTP {self.status_code}")


def _live_payload() -> dict:
    return {
        "status": "ok",
        "message": {
            "items": [
                {
                    "DOI": "10.9999/live.1",
                    "title": ["Live Crossref Paper About Retrieval"],
                    "abstract": "<jats:p>A live abstract that is long enough to pass cleaning.</jats:p>",
                    "author": [{"given": "Lan", "family": "Tran"}],
                    "subject": ["Information Retrieval"],
                    "published": {"date-parts": [[2026, 9, 1]]},
                }
            ]
        },
    }


def test_parser_reproduces_committed_records(settings):
    records = parse_crossref_payload(read_json(settings.paths.raw_api_response))
    assert len(records) == 24
    assert [asdict(record) for record in records] == read_json(settings.paths.raw_records_json)


def test_parser_cleans_markup_and_normalizes_fields():
    payload = {
        "status": "ok",
        "message": {
            "items": [
                {
                    "DOI": "https://doi.org/10.1234/ABC.5",
                    "title": ["  A <i>Study</i> of   RAG &amp; Agents "],
                    "abstract": "<jats:title>Abstract</jats:title><jats:p>We study  H<sub>2</sub>O.</jats:p><jats:p>Second para.</jats:p>",
                    "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "Crossref Team"}, {"given": "Ada", "family": "Lovelace"}],
                    "subject": [],
                    "type": "journal-article",
                    "published": {"date-parts": [[2026, 5]]},
                    "deposited": {"date-parts": [[2026, 6, 2]]},
                    "link": [{"URL": "https://example.org/paper.pdf", "content-type": "application/pdf"}],
                }
            ]
        },
    }
    [record] = parse_crossref_payload(payload)
    assert record.paper_id == "10.1234/abc.5"
    assert record.title == "A Study of RAG & Agents"
    assert record.summary == "We study H2O. Second para."
    assert record.authors == ["Ada Lovelace", "Crossref Team"]
    assert record.categories == ["Journal Article"]
    assert record.primary_category == "Journal Article"
    assert record.published == "2026-05-01"
    assert record.updated == "2026-06-02"
    assert record.abs_url == "https://doi.org/10.1234/abc.5"
    assert record.pdf_url == "https://example.org/paper.pdf"


def test_parser_skips_invalid_items_and_handles_date_fallbacks():
    base = {"DOI": "10.1/x", "title": ["Valid Title Here"], "abstract": "Abstract: Plain text abstract without tags."}
    payload = {
        "message": {
            "items": [
                {**base, "created": {"date-time": "2025-01-02T10:00:00Z"}},
                {**base, "DOI": ""},
                {**base, "abstract": None, "published": {"date-parts": [[2026, 1, 1]]}},
                {**base, "title": [], "published": {"date-parts": [[2026, 1, 1]]}},
                {**base, "published": {"date-parts": [[2026, 13, 40]]}},
                "not-a-dict",
            ]
        }
    }
    records = parse_crossref_payload(payload)
    assert len(records) == 1
    assert records[0].published == "2025-01-02"
    assert records[0].summary == "Plain text abstract without tags."
    assert records[0].categories == ["Uncategorized"]


@pytest.mark.parametrize("payload", [{"foo": 1}, {"status": "failed", "message": {}}, []])
def test_parser_rejects_unexpected_payloads(payload):
    with pytest.raises(ValueError):
        parse_crossref_payload(payload)


def test_fetch_uses_snapshot_by_default(settings, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("snapshot mode must not call the API")

    monkeypatch.setattr(crossref.requests, "get", no_network)
    records = fetch_source_records(settings)
    manifest = read_json(ingestion_manifest_path(settings))
    assert len(records) == 24
    assert manifest["mode"] == "snapshot"
    assert manifest["valid_records"] == 24
    assert manifest["raw_records_rewritten"] is False
    assert manifest["raw_api_response"] == "data/raw/crossref_response.json"


def test_fetch_live_retries_then_preserves_raw_bytes(settings, monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(503), FakeResponse(200, _live_payload())]
    sleeps: list[float] = []
    monkeypatch.setattr(crossref.requests, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(crossref.time, "sleep", sleeps.append)
    monkeypatch.setenv("CROSSREF_MAILTO", "lab@example.org")

    records = fetch_source_records(replace(settings, refresh_source=True))
    manifest = read_json(ingestion_manifest_path(settings))
    assert [record.paper_id for record in records] == ["10.9999/live.1"]
    assert manifest["mode"] == "live"
    assert manifest["attempts"] == 3
    assert sleeps == [1.0, 4.0]
    assert settings.paths.raw_api_response.read_bytes() == json.dumps(_live_payload()).encode("utf-8")
    assert manifest["archived_previous_snapshot"].startswith("data/raw/archive/crossref_response_")
    assert read_json(settings.paths.raw_records_json)[0]["paper_id"] == "10.9999/live.1"


def test_fetch_falls_back_to_snapshot_when_api_is_down(settings, monkeypatch):
    calls = []

    def offline(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(crossref.requests, "get", offline)
    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    snapshot = settings.paths.raw_api_response.read_bytes()

    records = fetch_source_records(replace(settings, refresh_source=True))
    manifest = read_json(ingestion_manifest_path(settings))
    assert len(records) == 24
    assert len(calls) == crossref.MAX_ATTEMPTS
    assert manifest["mode"] == "snapshot_fallback"
    assert "ConnectionError" in manifest["fallback_reason"]
    assert settings.paths.raw_api_response.read_bytes() == snapshot


def test_fetch_falls_back_on_non_retryable_status(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(crossref.requests, "get", lambda *args, **kwargs: calls.append(1) or FakeResponse(400))
    records = fetch_source_records(replace(settings, refresh_source=True))
    assert len(records) == 24
    assert len(calls) == 1


def test_live_payload_without_valid_records_keeps_snapshot(settings, monkeypatch):
    empty = {"status": "ok", "message": {"items": []}}
    monkeypatch.setattr(crossref.requests, "get", lambda *args, **kwargs: FakeResponse(200, empty))
    snapshot = settings.paths.raw_api_response.read_bytes()
    records = fetch_source_records(replace(settings, refresh_source=True))
    assert len(records) == 24
    assert settings.paths.raw_api_response.read_bytes() == snapshot


def test_fetch_without_snapshot_and_network_raises(settings, monkeypatch):
    settings.paths.raw_api_response.unlink()
    monkeypatch.setattr(crossref.requests, "get", lambda *args, **kwargs: FakeResponse(500))
    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="no snapshot"):
        fetch_source_records(settings)


def test_load_raw_records_fills_missing_fields(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps([{"paper_id": "10.1/x", "title": "T", "categories": ["A"], "extra": 1}, "skip-me"]), encoding="utf-8")
    [record] = load_raw_records(path)
    assert record.authors == []
    assert record.primary_category == "A"
    assert record.summary == ""

    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_raw_records(path)
