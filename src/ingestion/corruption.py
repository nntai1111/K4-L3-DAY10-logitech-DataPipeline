from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path: Path | str) -> pd.DataFrame:
    """Giả lập 6 kịch bản tiêm lỗi dữ liệu thực tế."""
    if df.empty:
        raise ValueError("Cannot corrupt an empty dataframe.")

    corrupted_df = df.copy()
    original_count = len(df)

    # Sort by published descending
    if "published" in corrupted_df.columns:
        corrupted_df = corrupted_df.sort_values(by="published", ascending=False).reset_index(drop=True)

    # 1. Drop latest 20% records
    num_drop = max(1, int(len(corrupted_df) * 0.2))
    corrupted_df = corrupted_df.iloc[num_drop:].reset_index(drop=True)

    remaining_count = len(corrupted_df)

    # 2. Blank summary on ~20% of rows
    blank_count = max(1, int(remaining_count * 0.2))
    for i in range(blank_count):
        corrupted_df.at[i, "summary"] = ""

    # 3. Inject text noise on ~20% of rows
    noise_count = max(1, int(remaining_count * 0.2))
    for i in range(blank_count, min(blank_count + noise_count, remaining_count)):
        corrupted_df.at[i, "summary"] = str(corrupted_df.at[i, "summary"]) + " [NOISE_CORRUPTION_GARBAGE_K4_DAY10_ERR]"

    # 4. Truncate title < 10 chars on ~15% of rows
    trunc_count = max(1, int(remaining_count * 0.15))
    for i in range(min(trunc_count, remaining_count)):
        curr_title = str(corrupted_df.at[i, "title"])
        corrupted_df.at[i, "title"] = curr_title[:5] if len(curr_title) >= 5 else "Err"

    # 5. Stale date: shift published date to 5 years ago (1825 days) on > 30% of rows
    stale_count = max(1, int(remaining_count * 0.35))
    for i in range(stale_count):
        corrupted_df.at[i, "published"] = "2021-01-01"
        corrupted_df.at[i, "age_days"] = int(corrupted_df.at[i, "age_days"]) + 1825

    # 6. Duplicate rows: duplicate top 2 rows to break uniqueness
    dup_count = min(2, remaining_count)
    duplicates = corrupted_df.iloc[:dup_count].copy()
    corrupted_df = pd.concat([corrupted_df, duplicates], ignore_index=True)

    # Rebuild summary_chars and text_for_embedding for all rows
    rebuilt_texts = []
    rebuilt_chars = []
    for idx, row in corrupted_df.iterrows():
        title = str(row["title"])
        summary = str(row["summary"])
        authors_joined = str(row.get("authors_joined", ""))
        published = str(row["published"])
        categories_joined = str(row.get("categories_joined", ""))

        text_for_embed = (
            f"Title: {title}\n"
            f"Authors: {authors_joined}\n"
            f"Published: {published}\n"
            f"Categories: {categories_joined}\n"
            f"Summary: {summary}"
        )
        rebuilt_texts.append(text_for_embed)
        rebuilt_chars.append(len(summary))

    corrupted_df["text_for_embedding"] = rebuilt_texts
    corrupted_df["summary_chars"] = rebuilt_chars

    # Build corruption log
    log_data = {
        "total_original_rows": original_count,
        "total_corrupted_rows": len(corrupted_df),
        "scenarios_applied": [
            "1. Drop latest 20% records (simulating stale data loss)",
            "2. Blank summary on 20% records (simulating missing text)",
            "3. Inject text noise into summary (simulating character noise)",
            "4. Truncate title to < 10 chars (simulating truncated titles)",
            "5. Stale date shifted 5 years back (simulating outdated SLA)",
            "6. Duplicate rows added (simulating duplicate paper_ids)",
        ],
        "actions_count": {
            "dropped_records": num_drop,
            "blank_summary_count": blank_count,
            "injected_noise_count": noise_count,
            "truncated_title_count": trunc_count,
            "stale_date_count": stale_count,
            "duplicate_rows_count": dup_count,
        },
    }

    out_path = Path(output_log_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return corrupted_df

