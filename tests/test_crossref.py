from __future__ import annotations

import copy
from dataclasses import asdict, replace
import json

import pytest
import requests

from core.utils import read_json, write_json
from ingestion import crossref
from ingestion.crossref import (
    PaperRecord,
    fetch_source_records,
    fetch_source_records_with_mode,
    load_raw_records,
    normalize_doi,
    parse_crossref_payload,
    strip_markup,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None, raises: bool = True):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self._raises = raises

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self._raises and self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def _item(**overrides) -> dict:
    item = {
        "DOI": "10.1000/Example.1",
        "title": ["  A   Paper  Title  "],
        "abstract": "<jats:p>First sentence here. Second one.</jats:p>",
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "subject": ["Computing", "  "],
        "published": {"date-parts": [[2026, 5, 20]]},
        "URL": "https://doi.org/10.1000/example.1",
    }
    item.update(overrides)
    return item


def _payload(*items: dict) -> dict:
    return {"message": {"items": list(items)}}


# --- DOI normalisation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1145/ABC.123", "10.1145/abc.123"),
        ("https://doi.org/10.1145/ABC", "10.1145/abc"),
        ("http://doi.org/10.1145/abc", "10.1145/abc"),
        ("https://dx.doi.org/10.1145/abc", "10.1145/abc"),
        ("HTTP://DX.DOI.ORG/10.1145/Abc", "10.1145/abc"),
        ("doi:10.1145/abc", "10.1145/abc"),
        ("  https://doi.org/10.1145/abc  ", "10.1145/abc"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


# --- JATS / HTML stripping ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<jats:p>Plain abstract.</jats:p>", "Plain abstract."),
        ("<jats:title>Abstract</jats:title><jats:p>Text  with\n spaces</jats:p>", "Abstract Text with spaces"),
        ("<jats:p>A &amp; B &lt;tag&gt; &quot;q&quot;</jats:p>", 'A & B <tag> "q"'),
        ("No<i>space</i>between", "No space between"),
        ("", ""),
        (None, ""),
    ],
)
def test_strip_markup(raw, expected):
    assert strip_markup(raw) == expected


# --- Crossref date parts -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("date_field", "expected"),
    [
        ({"date-parts": [[2026, 5, 20]]}, "2026-05-20"),
        ({"date-parts": [[2026, 5]]}, "2026-05-01"),
        ({"date-parts": [[2026]]}, "2026-01-01"),
        ({"date-parts": [[2026, None, None]]}, "2026-01-01"),
        ({"date-parts": [[2026, 7, None]]}, "2026-07-01"),
        ({"date-parts": [[None]], "date-time": "2026-03-04T10:00:00Z"}, "2026-03-04"),
        ({"date-time": "2026-03-04T10:00:00Z"}, "2026-03-04"),
        ({"date-parts": [[]]}, ""),
        ({}, ""),
        (None, ""),
    ],
)
def test_iso_date_handles_missing_parts(date_field, expected):
    assert crossref._iso_date_from_crossref(date_field) == expected


def test_first_date_follows_priority_order():
    item = {
        "created": {"date-time": "2026-01-01T00:00:00Z"},
        "published-online": {"date-parts": [[2026, 2, 2]]},
    }
    assert crossref._first_date(item, crossref.DATE_FIELDS_BY_PRIORITY) == "2026-02-02"
    item["published"] = {"date-parts": [[2026, 3, 3]]}
    assert crossref._first_date(item, crossref.DATE_FIELDS_BY_PRIORITY) == "2026-03-03"
    assert crossref._first_date({}, crossref.DATE_FIELDS_BY_PRIORITY) == ""


# --- Payload parsing ---------------------------------------------------------------------------


def test_parse_builds_a_normalised_record():
    [record] = parse_crossref_payload(_payload(_item()))
    assert record == PaperRecord(
        paper_id="10.1000/example.1",
        title="A Paper Title",
        summary="First sentence here. Second one.",
        authors=["Ada Lovelace"],
        categories=["Computing"],
        primary_category="Computing",
        published="2026-05-20",
        updated="2026-05-20",
        abs_url="https://doi.org/10.1000/example.1",
        pdf_url="https://doi.org/10.1000/example.1",
        comment="Crossref record 10.1000/example.1",
    )


@pytest.mark.parametrize(
    "broken",
    [
        {"abstract": None},
        {"abstract": ""},
        {"abstract": "<jats:p>   </jats:p>"},
        {"DOI": ""},
        {"title": []},
        {"title": ["   "]},
        {"published": None},
    ],
    ids=["abstract-none", "abstract-empty", "abstract-only-markup", "no-doi", "no-title", "blank-title", "no-date"],
)
def test_parse_skips_incomplete_items(broken):
    records = parse_crossref_payload(_payload(_item(**broken), _item(DOI="10.1000/kept")))
    assert [record.paper_id for record in records] == ["10.1000/kept"]


def test_parse_skips_item_without_abstract_key():
    item = _item()
    del item["abstract"]
    records = parse_crossref_payload(_payload(item, _item(DOI="10.1000/kept")))
    assert [record.paper_id for record in records] == ["10.1000/kept"]


def test_parse_optional_fields_and_fallbacks():
    item = _item(
        DOI="https://doi.org/10.1000/X",
        author=[{"name": "  Research   Group "}, {"given": "Solo"}, {"family": ""}, {}],
        subject=None,
        link=[
            {"content-type": "text/html", "URL": "https://example.org/html"},
            {"content-type": "application/pdf", "URL": "https://example.org/paper.pdf"},
        ],
        deposited={"date-parts": [[2026, 6, 1]]},
    )
    del item["URL"]
    [record] = parse_crossref_payload(_payload(item))
    assert record.authors == ["Research Group", "Solo"]
    assert record.categories == [] and record.primary_category == ""
    assert record.abs_url == "https://doi.org/10.1000/x"
    assert record.pdf_url == "https://example.org/paper.pdf"
    assert record.updated == "2026-06-01"


def test_parse_handles_an_empty_payload():
    assert parse_crossref_payload({}) == []
    assert parse_crossref_payload({"message": {}}) == []


def test_snapshot_parses_to_the_committed_records(raw_payload, committed_records):
    records = parse_crossref_payload(raw_payload)
    assert len(records) == 24
    assert [asdict(record) for record in records] == committed_records


def test_snapshot_parse_does_not_mutate_the_payload(raw_payload):
    before = copy.deepcopy(raw_payload)
    parse_crossref_payload(raw_payload)
    assert raw_payload == before


# --- Round trip through crossref_records.json ---------------------------------------------------


def test_load_raw_records_round_trip(tmp_path, raw_payload):
    records = parse_crossref_payload(raw_payload)
    path = tmp_path / "records.json"
    write_json(path, [asdict(record) for record in records])
    assert load_raw_records(path) == records


def test_load_raw_records_ignores_unknown_keys(tmp_path, committed_records):
    rows = [dict(row, extra_column="ignored", another=1) for row in committed_records[:2]]
    path = tmp_path / "records.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    loaded = load_raw_records(path)
    assert [asdict(record) for record in loaded] == committed_records[:2]


# --- Fetch: snapshot, live, and fallback -------------------------------------------------------


def _forbid_network(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("requests.get must not be called in snapshot mode")

    monkeypatch.setattr(crossref.requests, "get", fail)


def test_fetch_uses_snapshot_when_refresh_is_unset(settings, monkeypatch, committed_records):
    assert settings.refresh_source is False
    _forbid_network(monkeypatch)
    settings.paths.raw_records_json.unlink()

    records, mode = fetch_source_records_with_mode(settings)

    assert mode == "snapshot"
    assert len(records) == 24
    assert read_json(settings.paths.raw_records_json) == committed_records


def test_refresh_source_env_flag_is_parsed(project_dir, monkeypatch):
    from core.config import load_settings

    for value, expected in [("1", True), ("true", True), ("YES", True), ("0", False), ("", False)]:
        monkeypatch.setenv("REFRESH_SOURCE", value)
        assert load_settings(project_dir).refresh_source is expected


def test_fetch_source_records_returns_only_records(settings, monkeypatch):
    _forbid_network(monkeypatch)
    records = fetch_source_records(settings)
    assert len(records) == 24 and all(isinstance(record, PaperRecord) for record in records)


def test_fetch_live_success_overwrites_snapshot(settings, monkeypatch):
    live_payload = _payload(_item(DOI="10.1000/live"))
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(200, live_payload)

    monkeypatch.setattr(crossref.requests, "get", fake_get)
    records, mode = fetch_source_records_with_mode(replace(settings, refresh_source=True))

    assert mode == "live"
    assert [record.paper_id for record in records] == ["10.1000/live"]
    assert read_json(settings.paths.raw_api_response) == live_payload
    assert len(calls) == 1
    assert calls[0]["url"] == crossref.CROSSREF_WORKS_URL
    assert calls[0]["params"] == {"query": settings.source_query, "filter": settings.source_filter, "rows": settings.max_results}


@pytest.mark.parametrize(
    "error",
    [requests.ConnectionError("no network"), requests.Timeout("slow"), ValueError("bad json"), RuntimeError("boom")],
    ids=["connection", "timeout", "value", "runtime"],
)
def test_fetch_falls_back_to_snapshot_when_live_call_raises(settings, monkeypatch, raw_payload, error):
    def failing_get(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(crossref.requests, "get", failing_get)
    records, mode = fetch_source_records_with_mode(replace(settings, refresh_source=True))

    assert mode == "snapshot"
    assert len(records) == 24
    assert read_json(settings.paths.raw_api_response) == raw_payload


def test_fetch_retries_retryable_status_then_falls_back(settings, monkeypatch, raw_payload):
    responses = iter([FakeResponse(503), FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(503)])
    sleeps: list[float] = []
    monkeypatch.setattr(crossref.requests, "get", lambda *_a, **_k: next(responses))
    monkeypatch.setattr(crossref.time, "sleep", sleeps.append)

    records, mode = fetch_source_records_with_mode(replace(settings, refresh_source=True))

    assert mode == "snapshot" and len(records) == 24
    assert sleeps == [2.0, 7.0]  # exponential backoff, then the server's Retry-After
    assert read_json(settings.paths.raw_api_response) == raw_payload


def test_fetch_retry_recovers_on_a_later_attempt(settings, monkeypatch):
    live_payload = _payload(_item(DOI="10.1000/after-retry"))
    responses = iter([FakeResponse(502), FakeResponse(200, live_payload)])
    monkeypatch.setattr(crossref.requests, "get", lambda *_a, **_k: next(responses))
    monkeypatch.setattr(crossref.time, "sleep", lambda _seconds: None)

    records, mode = fetch_source_records_with_mode(replace(settings, refresh_source=True))
    assert mode == "live" and [record.paper_id for record in records] == ["10.1000/after-retry"]


def test_fetch_does_not_retry_a_client_error(settings, monkeypatch):
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        return FakeResponse(404)

    monkeypatch.setattr(crossref.requests, "get", fake_get)
    monkeypatch.setattr(crossref.time, "sleep", lambda _seconds: pytest.fail("must not sleep on a 404"))
    _records, mode = fetch_source_records_with_mode(replace(settings, refresh_source=True))
    assert mode == "snapshot" and len(calls) == 1


def test_live_fetch_raises_after_exhausting_retries_without_http_error(settings, monkeypatch):
    monkeypatch.setattr(crossref.requests, "get", lambda *_a, **_k: FakeResponse(503, raises=False))
    monkeypatch.setattr(crossref.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="exhausted"):
        crossref._fetch_live_payload(settings)


def test_live_fetch_names_the_contact_when_mailto_is_set(settings, monkeypatch):
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append({"params": params, "headers": headers})
        return FakeResponse(200, _payload(_item(DOI="10.1000/polite")))

    monkeypatch.setattr(crossref.requests, "get", fake_get)
    crossref._fetch_live_payload(replace(settings, crossref_mailto="team@example.org"))

    assert calls[0]["params"]["mailto"] == "team@example.org"
    assert calls[0]["headers"]["User-Agent"].endswith("(mailto:team@example.org)")


def test_crossref_mailto_env_is_read(project_dir, monkeypatch):
    from core.config import load_settings

    monkeypatch.setenv("CROSSREF_MAILTO", "team@example.org")
    assert load_settings(project_dir).crossref_mailto == "team@example.org"
    monkeypatch.setenv("CROSSREF_MAILTO", "")
    assert load_settings(project_dir).crossref_mailto is None
