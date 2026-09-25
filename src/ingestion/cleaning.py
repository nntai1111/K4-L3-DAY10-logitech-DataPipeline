from __future__ import annotations

from datetime import datetime, timezone
import re

import pandas as pd

from ingestion.crossref import PaperRecord


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    return " ".join(cleaned.split())


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records thanh dataframe san sang de embed."""
    rows = []
    run_date_naive = run_date.replace(tzinfo=None) if run_date.tzinfo else run_date

    for r in records:
        paper_id = r.paper_id.strip()
        if not paper_id:
            continue

        title = _clean_text(r.title)
        summary = _clean_text(r.summary)
        authors = [a.strip() for a in r.authors if a.strip()]
        authors_joined = ", ".join(authors)

        categories = [c.strip() for c in r.categories if c.strip()]
        categories_joined = ", ".join(categories)
        primary_category = r.primary_category.strip() or (categories[0] if categories else "General")

        published_str = r.published.strip() or "2026-01-01"
        try:
            pub_dt = datetime.strptime(published_str[:10], "%Y-%m-%d")
        except Exception:
            pub_dt = run_date_naive

        age_days = (run_date_naive - pub_dt).days
        age_days = max(0, age_days)

        summary_chars = len(summary)

        text_for_embedding = (
            f"Title: {title}\n"
            f"Authors: {authors_joined}\n"
            f"Published: {published_str}\n"
            f"Categories: {categories_joined}\n"
            f"Summary: {summary}"
        )

        rows.append(
            {
                "paper_id": paper_id,
                "title": title,
                "summary": summary,
                "authors": authors,
                "categories": categories,
                "primary_category": primary_category,
                "published": published_str,
                "updated": r.updated.strip() or published_str,
                "abs_url": r.abs_url.strip(),
                "pdf_url": r.pdf_url.strip(),
                "comment": r.comment.strip(),
                "age_days": age_days,
                "authors_joined": authors_joined,
                "categories_joined": categories_joined,
                "summary_chars": summary_chars,
                "text_for_embedding": text_for_embedding,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.drop_duplicates(subset=["paper_id"], keep="first")
    df = df[(df["paper_id"].str.len() > 0) & (df["title"].str.len() > 0)]
    df = df.sort_values(by="published", ascending=False).reset_index(drop=True)

    return df

