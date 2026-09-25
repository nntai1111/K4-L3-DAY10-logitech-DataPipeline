from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime

import pandas as pd

from core.utils import compact_join, normalize_whitespace
from ingestion.crossref import PaperRecord, strip_markup

# Column order is the data contract every downstream step reads (index, quality gate, test set).
CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
    "comment",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "age_days",
    "text_for_embedding",
]


def build_text_for_embedding(row: dict | pd.Series) -> str:
    return "\n".join(
        [
            f"Title: {row['title']}",
            f"Authors: {row['authors_joined']}",
            f"Published: {row['published']}",
            f"Categories: {row['categories_joined']}",
            f"Summary: {row['summary']}",
        ]
    )


def refresh_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute the columns built from other columns, after cleaning or after a corruption edits them."""
    df = df.copy()
    if df.empty:
        return df.assign(summary_chars=pd.Series(dtype=int), text_for_embedding=pd.Series(dtype=str))
    df["summary_chars"] = df["summary"].str.len().astype(int)
    df["text_for_embedding"] = df.apply(build_text_for_embedding, axis=1)
    return df


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _clean_list(values: list[str]) -> list[str]:
    return [normalize_whitespace(value) for value in values or [] if normalize_whitespace(value)]


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Normalize raw records into the embedding-ready table.

    run_date is passed in rather than read from the clock, so that rebuilding from the same raw
    records on the same run_date always produces the same table (the repair step relies on this).
    """
    run_day = run_date.date() if isinstance(run_date, datetime) else run_date
    rows = []
    for record in records:
        row = asdict(record)
        row["paper_id"] = normalize_whitespace(row["paper_id"]).lower()
        row["title"] = normalize_whitespace(row["title"])
        row["summary"] = strip_markup(row["summary"])
        row["authors"] = _clean_list(row["authors"])
        row["categories"] = _clean_list(row["categories"])
        row["primary_category"] = normalize_whitespace(row["primary_category"]) or (row["categories"] or [""])[0]

        published_day = _parse_iso_date(row["published"])
        if not (row["paper_id"] and row["title"] and published_day):
            continue
        updated_day = _parse_iso_date(row["updated"]) or published_day
        row["published"] = published_day.isoformat()
        row["updated"] = updated_day.isoformat()
        row["age_days"] = (run_day - published_day).days
        row["authors_joined"] = compact_join(row["authors"])
        row["categories_joined"] = compact_join(row["categories"])
        for text_column in ("abs_url", "pdf_url", "comment"):
            row[text_column] = row[text_column] or ""
        rows.append(row)

    df = pd.DataFrame(rows, columns=[column for column in CLEAN_COLUMNS if column not in {"summary_chars", "text_for_embedding"}])
    df = df.drop_duplicates(subset="paper_id", keep="first")
    df = refresh_derived_columns(df)
    df = df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    return df[CLEAN_COLUMNS]
