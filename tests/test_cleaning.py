from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pandas as pd

from ingestion.cleaning import CLEAN_COLUMNS, build_clean_dataframe, build_text_for_embedding, refresh_derived_columns
from ingestion.crossref import PaperRecord
from pipelines.common import table_sha256


def _record(**overrides) -> PaperRecord:
    record = PaperRecord(
        paper_id="10.1000/a",
        title="A Title Long Enough",
        summary="A summary that is long enough to pass. Second sentence.",
        authors=["Ada Lovelace"],
        categories=["Computing"],
        primary_category="Computing",
        published="2026-06-01",
        updated="2026-06-02",
        abs_url="https://doi.org/10.1000/a",
        pdf_url="https://doi.org/10.1000/a",
        comment="c",
    )
    return replace(record, **overrides)


def test_snapshot_cleans_to_24_rows_in_contract_order(clean_df):
    assert len(clean_df) == 24
    assert list(clean_df.columns) == CLEAN_COLUMNS
    assert clean_df["paper_id"].is_unique
    assert clean_df.index.tolist() == list(range(24))


def test_rows_sorted_newest_first_then_by_paper_id(clean_df):
    expected = clean_df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    pd.testing.assert_frame_equal(clean_df, expected)


def test_age_days_counts_from_the_run_date(clean_df, run_date):
    for published, age in zip(clean_df["published"], clean_df["age_days"], strict=True):
        assert age == (run_date - date.fromisoformat(published)).days
    assert clean_df["age_days"].min() == 65 and clean_df["age_days"].max() == 181


def test_derived_columns_match_their_sources(clean_df):
    for row in clean_df.to_dict(orient="records"):
        assert row["summary_chars"] == len(row["summary"])
        assert row["authors_joined"] == ", ".join(row["authors"])
        assert row["categories_joined"] == ", ".join(row["categories"])
        assert row["text_for_embedding"] == build_text_for_embedding(row)
        assert "<" not in row["summary"], "JATS markup must be stripped"


def test_text_for_embedding_layout():
    row = {"title": "T", "authors_joined": "A, B", "published": "2026-01-01", "categories_joined": "C", "summary": "S."}
    assert build_text_for_embedding(row) == "Title: T\nAuthors: A, B\nPublished: 2026-01-01\nCategories: C\nSummary: S."


def test_same_input_and_run_date_gives_the_same_table(records, run_date):
    first = build_clean_dataframe(records, run_date)
    second = build_clean_dataframe(list(reversed(records)), run_date)
    pd.testing.assert_frame_equal(first, second)
    assert table_sha256(first) == table_sha256(second)


def test_run_date_accepts_date_or_datetime(records, run_date):
    as_datetime = datetime(run_date.year, run_date.month, run_date.day, 23, 59)
    pd.testing.assert_frame_equal(build_clean_dataframe(records, run_date), build_clean_dataframe(records, as_datetime))


def test_a_later_run_date_only_changes_age(records, run_date):
    today = build_clean_dataframe(records, run_date)
    later = build_clean_dataframe(records, run_date + timedelta(days=10))
    assert (later["age_days"] - today["age_days"]).eq(10).all()
    pd.testing.assert_frame_equal(today.drop(columns="age_days"), later.drop(columns="age_days"))


def test_normalises_text_and_lists(run_date):
    [row] = build_clean_dataframe(
        [
            _record(
                paper_id="  10.1000/MiXeD ",
                title="  Spaced    Title  Here ",
                summary="<jats:p>Tagged &amp; spaced   summary text for the check.</jats:p>",
                authors=[" Ada  Lovelace ", "", "  "],
                categories=["  Computing ", ""],
                primary_category="",
                abs_url="",
                pdf_url="",
                comment="",
            )
        ],
        run_date,
    ).to_dict(orient="records")
    assert row["paper_id"] == "10.1000/mixed"
    assert row["title"] == "Spaced Title Here"
    assert row["summary"] == "Tagged & spaced summary text for the check."
    assert row["authors"] == ["Ada Lovelace"]
    assert row["categories"] == ["Computing"]
    assert row["primary_category"] == "Computing"
    assert (row["abs_url"], row["pdf_url"], row["comment"]) == ("", "", "")


def test_drops_rows_without_id_title_or_valid_date(run_date):
    df = build_clean_dataframe(
        [
            _record(paper_id="10.1000/kept"),
            _record(paper_id="   "),
            _record(paper_id="10.1000/no-title", title="  "),
            _record(paper_id="10.1000/bad-date", published="not-a-date"),
        ],
        run_date,
    )
    assert df["paper_id"].tolist() == ["10.1000/kept"]


def test_bad_updated_date_falls_back_to_published(run_date):
    [row] = build_clean_dataframe([_record(updated="garbage")], run_date).to_dict(orient="records")
    assert row["updated"] == row["published"] == "2026-06-01"


def test_timestamps_are_cut_to_the_day(run_date):
    [row] = build_clean_dataframe([_record(published="2026-06-01T12:30:00Z", updated="2026-06-03T00:00:00Z")], run_date).to_dict(orient="records")
    assert (row["published"], row["updated"]) == ("2026-06-01", "2026-06-03")


def test_duplicate_paper_ids_keep_the_first(run_date):
    df = build_clean_dataframe([_record(title="First Title Wins"), _record(paper_id="10.1000/A", title="Second Title Loses")], run_date)
    assert df["title"].tolist() == ["First Title Wins"]


def test_no_records_gives_an_empty_table_with_the_contract(run_date):
    df = build_clean_dataframe([], run_date)
    assert df.empty
    assert list(df.columns) == CLEAN_COLUMNS


def test_refresh_derived_columns_recomputes_after_edit(clean_df):
    edited = clean_df.copy()
    edited.loc[0, "summary"] = "short"
    edited.loc[0, "title"] = "Edited"
    refreshed = refresh_derived_columns(edited)
    assert refreshed.loc[0, "summary_chars"] == 5
    assert refreshed.loc[0, "text_for_embedding"].startswith("Title: Edited\n")
    assert clean_df.loc[0, "summary"] != "short", "refresh must not mutate its input"


def test_refresh_derived_columns_on_empty_frame():
    empty = pd.DataFrame(columns=CLEAN_COLUMNS)
    refreshed = refresh_derived_columns(empty)
    assert refreshed.empty and {"summary_chars", "text_for_embedding"} <= set(refreshed.columns)
