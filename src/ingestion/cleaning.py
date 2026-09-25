from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import compact_join, normalize_whitespace, read_json, write_csv, write_json
from ingestion.crossref import PaperRecord

MIN_TITLE_CHARS = 8
MIN_SUMMARY_CHARS = 30
LIST_COLUMNS = ("authors", "categories")
BASE_COLUMNS = [
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
]
CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "age_days",
    "abs_url",
    "pdf_url",
    "comment",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "text_for_embedding",
]
# Content that defines "the same dataset"; age_days is excluded because it depends on the run date.
FINGERPRINT_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors_joined",
    "categories_joined",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
    "text_for_embedding",
]
CLEANING_RULES = [
    "Normalize whitespace in every text field; lowercase paper_id (DOI).",
    "Deduplicate authors and categories while keeping their order; empty categories become 'Uncategorized'.",
    f"Drop rows without paper_id, with a title shorter than {MIN_TITLE_CHARS} chars, "
    f"a summary shorter than {MIN_SUMMARY_CHARS} chars, or an unparseable published date.",
    "Deduplicate by paper_id, keeping the most recently updated version.",
    "age_days = (run_date - published).days; text_for_embedding = Title/Authors/Published/Categories/Summary.",
    "Sort by published (newest first), then paper_id.",
]


def _as_utc(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _clean_list(values: Any) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = normalize_whitespace(str(value))
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def build_text_for_embedding(
    title: str,
    authors_joined: str,
    published: str,
    categories_joined: str,
    summary: str,
) -> str:
    return "\n".join(
        [
            f"Title: {title}",
            f"Authors: {authors_joined}",
            f"Published: {published}",
            f"Categories: {categories_joined}",
            f"Summary: {summary}",
        ]
    )


def refresh_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute the helper columns from the base fields (after cleaning or after corruption)."""
    df = df.copy()
    df["authors_joined"] = df["authors"].map(compact_join)
    df["categories_joined"] = df["categories"].map(compact_join)
    df["summary_chars"] = df["summary"].fillna("").str.len().astype(int)
    df["text_for_embedding"] = [
        build_text_for_embedding(row.title, row.authors_joined, row.published, row.categories_joined, row.summary)
        for row in df.itertuples(index=False)
    ]
    return df


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Turn raw records into an embedding-ready dataframe (see CLEANING_RULES)."""
    run_timestamp = _as_utc(run_date)
    rows = [
        {
            "paper_id": normalize_whitespace(record.paper_id).lower(),
            "title": normalize_whitespace(record.title),
            "summary": normalize_whitespace(record.summary),
            "authors": _clean_list(record.authors),
            "categories": _clean_list(record.categories) or ["Uncategorized"],
            "primary_category": normalize_whitespace(record.primary_category),
            "published": record.published,
            "updated": record.updated,
            "abs_url": record.abs_url.strip(),
            "pdf_url": (record.pdf_url or record.abs_url).strip(),
            "comment": normalize_whitespace(record.comment),
        }
        for record in records
    ]
    df = pd.DataFrame(rows, columns=BASE_COLUMNS)
    input_rows = len(df)

    published = pd.to_datetime(df["published"], errors="coerce", utc=True, format="ISO8601")
    updated = pd.to_datetime(df["updated"], errors="coerce", utc=True, format="ISO8601").fillna(published)
    valid = (
        df["paper_id"].str.len().gt(0)
        & df["title"].str.len().ge(MIN_TITLE_CHARS)
        & df["summary"].str.len().ge(MIN_SUMMARY_CHARS)
        & published.notna()
    )
    df = df.loc[valid].copy()
    published = published.loc[valid]
    df["published"] = published.dt.strftime("%Y-%m-%d")
    df["updated"] = updated.loc[valid].dt.strftime("%Y-%m-%d")
    df["age_days"] = (run_timestamp - published).dt.days.astype(int)
    df["primary_category"] = [
        primary or categories[0] for primary, categories in zip(df["primary_category"], df["categories"])
    ]

    valid_rows = len(df)
    df = df.sort_values(["updated", "paper_id"], ascending=[False, True], kind="stable")
    df = df.drop_duplicates(subset="paper_id", keep="first")

    df = refresh_derived_columns(df)
    df = df.sort_values(["published", "paper_id"], ascending=[False, True], kind="stable")
    df = df.reset_index(drop=True)[CLEAN_COLUMNS]
    df.attrs["cleaning_stats"] = {
        "run_date": run_timestamp.isoformat(),
        "input_records": input_rows,
        "dropped_invalid": input_rows - valid_rows,
        "dropped_duplicates": valid_rows - len(df),
        "output_rows": len(df),
        "rules": CLEANING_RULES,
    }
    return df


def save_clean_dataframe(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    """Write the JSON (lists kept as arrays) and CSV (lists stored as JSON strings) artifacts."""
    write_json(json_path, json.loads(df.to_json(orient="records", force_ascii=False)))
    csv_df = df.copy()
    for column in LIST_COLUMNS:
        if column in csv_df.columns:
            csv_df[column] = csv_df[column].map(lambda values: json.dumps(list(values or []), ensure_ascii=False))
    write_csv(csv_df, csv_path)


def load_clean_dataframe(path: Path) -> pd.DataFrame:
    return pd.DataFrame(read_json(Path(path)))


def dataset_fingerprint(df: pd.DataFrame) -> str:
    """Order-independent SHA-256 of the dataset content, used to prove the repair is idempotent."""
    columns = [column for column in FINGERPRINT_COLUMNS if column in df.columns]
    canonical = df[columns].astype(str).sort_values(columns).to_dict(orient="records")
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
