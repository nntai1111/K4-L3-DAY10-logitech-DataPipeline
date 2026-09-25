from __future__ import annotations

from datetime import date, timedelta
import random
from typing import Any

import pandas as pd

from core.utils import write_json
from ingestion.cleaning import refresh_derived_columns

SEED = 42
DROP_LATEST_FRACTION = 0.20
BLANK_SUMMARY_ROWS = 3
NOISE_ROWS = 3
TRUNCATE_TITLE_ROWS = 3
# More than 25% of 24 rows must be stale for the freshness SLA to trip, so at least 7.
STALE_DATE_ROWS = 8
DUPLICATE_ROWS = 4
TRUNCATED_TITLE_CHARS = 7
STALE_SHIFT_DAYS = 365
NOISE_TOKENS = ["#@%", "~~&*", "$$^", "|<>|", "&&%$", "{[]}", "@@##", "%%~"]
NOISE_EVERY_N_WORDS = 3


def _inject_noise(summary: str, rng: random.Random) -> str:
    """Insert a junk token after every third word. The noise lands inside the first sentence,
    which is the one qa.py answers with, so it shows up in token F1 (noise at the end would not)."""
    words = summary.split()
    noisy_words: list[str] = []
    for position, word in enumerate(words, start=1):
        noisy_words.append(word)
        if position % NOISE_EVERY_N_WORDS == 0:
            noisy_words.append(rng.choice(NOISE_TOKENS))
    return " ".join(noisy_words)


def _shift_back(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) - timedelta(days=days)).isoformat()


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path, seed: int = SEED) -> pd.DataFrame:
    """Apply the six corruption scenarios to a copy of the clean table and log what each one touched.

    The four field-level scenarios after the drop target disjoint rows, so a wrong answer traces back
    to one of them; duplicate_rows copies any row and may overlap. Dropping 4 rows and duplicating 4 keeps the row count at 24, which is
    why the row-count expectation alone cannot see this damage.
    """
    rng = random.Random(seed)
    corrupted = df.copy().reset_index(drop=True)
    input_rows = len(corrupted)
    scenarios: list[dict[str, Any]] = []

    def log(name: str, description: str, paper_ids: list[str]) -> None:
        scenarios.append({"scenario": name, "description": description, "rows_affected": len(paper_ids), "paper_ids": paper_ids})

    drop_count = max(1, int(input_rows * DROP_LATEST_FRACTION))
    latest_ids = corrupted.sort_values(["published", "paper_id"], ascending=[False, True])["paper_id"].head(drop_count).tolist()
    corrupted = corrupted[~corrupted["paper_id"].isin(latest_ids)].reset_index(drop=True)
    log("drop_latest_records", f"Bỏ {drop_count} bài xuất bản gần nhất (mất dữ liệu tươi).", latest_ids)

    remaining_ids = sorted(corrupted["paper_id"])
    rng.shuffle(remaining_ids)
    cursor = 0

    def take(count: int) -> list[str]:
        nonlocal cursor
        chosen = remaining_ids[cursor : cursor + count]
        cursor += count
        return chosen

    def rows_for(paper_ids: list[str]) -> pd.Series:
        return corrupted["paper_id"].isin(paper_ids)

    blank_ids = take(BLANK_SUMMARY_ROWS)
    corrupted.loc[rows_for(blank_ids), "summary"] = ""
    log("blank_summary", "Xóa trắng summary thành chuỗi rỗng (bộ cào trả về rỗng).", blank_ids)

    noise_ids = take(NOISE_ROWS)
    noisy = rows_for(noise_ids)
    corrupted.loc[noisy, "summary"] = corrupted.loc[noisy, "summary"].map(lambda text: _inject_noise(text, rng))
    log("inject_text_noise", f"Chèn một cụm ký tự rác sau mỗi {NOISE_EVERY_N_WORDS} từ của summary.", noise_ids)

    truncate_ids = take(TRUNCATE_TITLE_ROWS)
    truncated = rows_for(truncate_ids)
    corrupted.loc[truncated, "title"] = corrupted.loc[truncated, "title"].str[:TRUNCATED_TITLE_CHARS]
    log("truncate_title", f"Cắt tiêu đề còn {TRUNCATED_TITLE_CHARS} ký tự đầu.", truncate_ids)

    stale_ids = take(STALE_DATE_ROWS)
    stale = rows_for(stale_ids)
    corrupted.loc[stale, "published"] = corrupted.loc[stale, "published"].map(lambda value: _shift_back(value, STALE_SHIFT_DAYS))
    # age_days = run_date - published, so moving published back N days adds exactly N days of age.
    corrupted.loc[stale, "age_days"] = corrupted.loc[stale, "age_days"] + STALE_SHIFT_DAYS
    log("stale_date", f"Lùi ngày xuất bản {STALE_SHIFT_DAYS} ngày, tính lại age_days.", stale_ids)

    duplicate_ids = sorted(rng.sample(sorted(corrupted["paper_id"]), DUPLICATE_ROWS))
    duplicates = corrupted[rows_for(duplicate_ids)]
    corrupted = pd.concat([corrupted, duplicates], ignore_index=True)
    log("duplicate_rows", f"Nhân bản {DUPLICATE_ROWS} dòng, trùng paper_id.", duplicate_ids)

    corrupted = refresh_derived_columns(corrupted)
    write_json(
        output_log_path,
        {
            "seed": seed,
            "input_rows": input_rows,
            "output_rows": len(corrupted),
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
        },
    )
    return corrupted
