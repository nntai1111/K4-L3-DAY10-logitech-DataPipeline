from __future__ import annotations

from datetime import datetime
import json

import pandas as pd

from ingestion.cleaning import (
    CLEAN_COLUMNS,
    build_clean_dataframe,
    dataset_fingerprint,
    load_clean_dataframe,
    refresh_derived_columns,
    save_clean_dataframe,
)
from ingestion.crossref import PaperRecord

from conftest import RUN_DATE


def _record(**overrides) -> PaperRecord:
    values = {
        "paper_id": "10.1/Base",
        "title": "A Sufficiently Long Title",
        "summary": "A summary that is comfortably longer than thirty characters.",
        "authors": ["Ann Le", "Ann Le", "  Binh   Tran "],
        "categories": [],
        "primary_category": "",
        "published": "2026-05-01",
        "updated": "2026-05-01",
        "abs_url": " https://doi.org/10.1/base ",
        "pdf_url": "",
        "comment": "c",
    }
    values.update(overrides)
    return PaperRecord(**values)


def test_snapshot_is_cleaned_into_embedding_ready_rows(clean_df):
    assert len(clean_df) == 24
    assert list(clean_df.columns) == CLEAN_COLUMNS
    assert clean_df["paper_id"].is_unique
    assert clean_df["published"].tolist() == sorted(clean_df["published"], reverse=True)
    newest = clean_df.iloc[0]
    assert newest["published"] == "2026-07-22"
    assert newest["age_days"] == 65
    lines = newest["text_for_embedding"].split("\n")
    assert [line.split(":")[0] for line in lines] == ["Title", "Authors", "Published", "Categories", "Summary"]
    assert clean_df.attrs["cleaning_stats"]["dropped_invalid"] == 0
    assert clean_df.attrs["cleaning_stats"]["dropped_duplicates"] == 0


def test_invalid_rows_are_dropped_and_latest_duplicate_wins():
    records = [
        _record(),
        _record(title="The Updated Version Of The Title", updated="2026-06-01"),
        _record(paper_id="10.1/short-summary", summary="too short"),
        _record(paper_id="10.1/short-title", title="Tiny"),
        _record(paper_id="10.1/bad-date", published="not-a-date"),
        _record(paper_id="   "),
    ]
    df = build_clean_dataframe(records, RUN_DATE)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["paper_id"] == "10.1/base"
    assert row["title"] == "The Updated Version Of The Title"
    assert row["authors"] == ["Ann Le", "Binh Tran"]
    assert row["categories"] == ["Uncategorized"]
    assert row["primary_category"] == "Uncategorized"
    assert row["abs_url"] == "https://doi.org/10.1/base"
    assert row["pdf_url"] == "https://doi.org/10.1/base"
    assert df.attrs["cleaning_stats"] | {"rules": []} == {
        "run_date": "2026-09-25T00:00:00+00:00",
        "input_records": 6,
        "dropped_invalid": 4,
        "dropped_duplicates": 1,
        "output_rows": 1,
        "rules": [],
    }


def test_naive_run_date_is_treated_as_utc(raw_records):
    naive = build_clean_dataframe(raw_records, datetime(2026, 9, 25))
    aware = build_clean_dataframe(raw_records, RUN_DATE)
    assert naive["age_days"].tolist() == aware["age_days"].tolist()


def test_save_and_load_round_trip(tmp_path, clean_df):
    csv_path, json_path = tmp_path / "clean.csv", tmp_path / "clean.json"
    save_clean_dataframe(clean_df, csv_path, json_path)
    loaded = load_clean_dataframe(json_path)
    assert dataset_fingerprint(loaded) == dataset_fingerprint(clean_df)
    assert loaded["authors"].iloc[0] == clean_df["authors"].iloc[0]
    csv_df = pd.read_csv(csv_path)
    assert json.loads(csv_df["authors"].iloc[0]) == clean_df["authors"].iloc[0]


def test_fingerprint_ignores_order_and_age_but_not_content(clean_df):
    shuffled = clean_df.sample(frac=1, random_state=7).assign(age_days=0)
    assert dataset_fingerprint(shuffled) == dataset_fingerprint(clean_df)
    changed = clean_df.copy()
    changed.loc[0, "summary"] = "different"
    assert dataset_fingerprint(changed) != dataset_fingerprint(clean_df)


def test_refresh_derived_columns_follows_base_fields(clean_df):
    df = clean_df.copy()
    df.loc[0, "summary"] = "New summary text."
    refreshed = refresh_derived_columns(df)
    assert refreshed.loc[0, "summary_chars"] == len("New summary text.")
    assert refreshed.loc[0, "text_for_embedding"].endswith("Summary: New summary text.")
