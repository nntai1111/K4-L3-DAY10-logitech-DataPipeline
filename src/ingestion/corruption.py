from __future__ import annotations

from pathlib import Path
import random
import string
from typing import Any, Iterable

import pandas as pd

from core.utils import now_utc, write_json
from ingestion.cleaning import refresh_derived_columns

SEED = 42
DROP_LATEST_FRACTION = 0.20
BLANK_SUMMARY_FRACTION = 0.15
NOISE_FRACTION = 0.15
TRUNCATE_TITLE_FRACTION = 0.15
STALE_DATE_FRACTION = 0.35
DUPLICATE_FRACTION = 0.15
TRUNCATED_TITLE_CHARS = 7
STALE_SHIFT_DAYS = 365
NOISE_WORD_PROBABILITY = 0.3
NOISE_SYMBOLS = "#@$%^&*~"
PREVIEW_CHARS = 90


def _count(total: int, fraction: float) -> int:
    return max(1, round(total * fraction)) if total else 0


def _preview(text: Any) -> str:
    text = str(text)
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 3] + "..."


class _RowPicker:
    """Hands out row positions without repetition, so each corruption hits different papers when possible."""

    def __init__(self, positions: Iterable[int], rng: random.Random):
        self._all = list(positions)
        self._pool = list(self._all)
        self._rng = rng
        rng.shuffle(self._pool)

    def take(self, count: int) -> list[int]:
        if count > len(self._pool):
            recycled = [position for position in self._all if position not in self._pool]
            self._rng.shuffle(recycled)
            self._pool += recycled
        chosen, self._pool = self._pool[:count], self._pool[count:]
        return sorted(chosen)


def _noise_token(rng: random.Random) -> str:
    symbols = "".join(rng.choice(NOISE_SYMBOLS) for _ in range(3))
    tail = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(3))
    return symbols + tail


def _inject_noise(text: str, rng: random.Random) -> str:
    words = text.split()
    if not words:
        return _noise_token(rng)
    noisy = [words[0], _noise_token(rng)]  # always hit the first sentence
    for word in words[1:]:
        noisy.append(word)
        if rng.random() < NOISE_WORD_PROBABILITY:
            noisy.append(_noise_token(rng))
    return " ".join(noisy)


def _event(
    step: int,
    kind: str,
    description: str,
    parameters: dict[str, Any],
    paper_ids: list[str],
    detected_by: list[str],
    examples: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "step": step,
        "type": kind,
        "description": description,
        "parameters": parameters,
        "affected_rows": len(paper_ids),
        "paper_ids": paper_ids,
        "detected_by": detected_by,
        "examples": examples[:3],
    }


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path, seed: int = SEED) -> pd.DataFrame:
    """Simulate six production data incidents on a copy of the clean dataset and log each one.

    Deterministic for a given seed, so reruns produce the same corrupted dataset.
    """
    rng = random.Random(seed)
    working = df.copy().reset_index(drop=True)
    input_rows = len(working)
    events: list[dict[str, Any]] = []

    # 1. Drop the newest records: fresh data silently stops arriving.
    order = (
        working.assign(_published=pd.to_datetime(working["published"], errors="coerce", format="ISO8601"))
        .sort_values(["_published", "paper_id"], ascending=[False, True])
        .index
    )
    drop_positions = list(order[: _count(len(working), DROP_LATEST_FRACTION)])
    dropped = working.loc[drop_positions]
    events.append(
        _event(
            1,
            "drop_latest_records",
            "Newest papers never reach the index (ingestion lost the freshest batch).",
            {"fraction": DROP_LATEST_FRACTION},
            dropped["paper_id"].tolist(),
            ["source_papers_present", "freshness.latest_published"],
            [{"paper_id": row.paper_id, "published": row.published} for row in dropped.itertuples()],
        )
    )
    working = working.drop(index=drop_positions).reset_index(drop=True)
    picker = _RowPicker(range(len(working)), rng)

    # 2. Blank summaries: the scraper returned empty abstracts.
    rows = picker.take(_count(len(working), BLANK_SUMMARY_FRACTION))
    examples = [{"paper_id": working.at[row, "paper_id"], "before": _preview(working.at[row, "summary"]), "after": ""} for row in rows]
    working.loc[rows, "summary"] = ""
    events.append(
        _event(
            2,
            "blank_summary",
            "Summary replaced by an empty string.",
            {"fraction": BLANK_SUMMARY_FRACTION},
            working.loc[rows, "paper_id"].tolist(),
            ["summary_min_length"],
            examples,
        )
    )

    # 3. Inject noise: encoding/OCR garbage inside the summary (and therefore text_for_embedding).
    rows = picker.take(_count(len(working), NOISE_FRACTION))
    examples = []
    for row in rows:
        before = working.at[row, "summary"]
        working.at[row, "summary"] = _inject_noise(before, rng)
        examples.append({"paper_id": working.at[row, "paper_id"], "before": _preview(before), "after": _preview(working.at[row, "summary"])})
    events.append(
        _event(
            3,
            "inject_noise",
            "Garbage symbol tokens inserted into the summary text.",
            {"fraction": NOISE_FRACTION, "word_probability": NOISE_WORD_PROBABILITY, "symbols": NOISE_SYMBOLS},
            working.loc[rows, "paper_id"].tolist(),
            ["summary_no_noise"],
            examples,
        )
    )

    # 4. Truncate titles below 8 characters.
    rows = picker.take(_count(len(working), TRUNCATE_TITLE_FRACTION))
    examples = []
    for row in rows:
        before = working.at[row, "title"]
        working.at[row, "title"] = before[:TRUNCATED_TITLE_CHARS].rstrip()
        examples.append({"paper_id": working.at[row, "paper_id"], "before": before, "after": working.at[row, "title"]})
    events.append(
        _event(
            4,
            "truncate_title",
            f"Title cut to its first {TRUNCATED_TITLE_CHARS} characters.",
            {"fraction": TRUNCATE_TITLE_FRACTION, "max_chars": TRUNCATED_TITLE_CHARS},
            working.loc[rows, "paper_id"].tolist(),
            ["title_min_length"],
            examples,
        )
    )

    # 5. Stale dates: published moved back one year, so the rows age past the freshness threshold.
    rows = picker.take(_count(len(working), STALE_DATE_FRACTION))
    examples = []
    for row in rows:
        before = working.at[row, "published"]
        working.at[row, "published"] = (pd.Timestamp(before) - pd.Timedelta(days=STALE_SHIFT_DAYS)).strftime("%Y-%m-%d")
        if "age_days" in working.columns:
            working.at[row, "age_days"] = int(working.at[row, "age_days"]) + STALE_SHIFT_DAYS
        examples.append({"paper_id": working.at[row, "paper_id"], "before": before, "after": working.at[row, "published"]})
    events.append(
        _event(
            5,
            "stale_date",
            f"Published date shifted back {STALE_SHIFT_DAYS} days.",
            {"fraction": STALE_DATE_FRACTION, "shift_days": STALE_SHIFT_DAYS},
            working.loc[rows, "paper_id"].tolist(),
            ["freshness_sla"],
            examples,
        )
    )

    # 6. Duplicate rows: the same batch was loaded twice.
    rows = sorted(rng.sample(range(len(working)), min(len(working), _count(len(working), DUPLICATE_FRACTION))))
    duplicates = working.loc[rows]
    working = pd.concat([working, duplicates], ignore_index=True)
    events.append(
        _event(
            6,
            "duplicate_rows",
            "Rows appended a second time with the same paper_id.",
            {"fraction": DUPLICATE_FRACTION},
            duplicates["paper_id"].tolist(),
            ["paper_id_unique"],
            [{"paper_id": paper_id} for paper_id in duplicates["paper_id"]],
        )
    )

    working = refresh_derived_columns(working)
    write_json(
        Path(output_log_path),
        {
            "generated_at": now_utc().isoformat(),
            "seed": seed,
            "input_rows": input_rows,
            "output_rows": len(working),
            "unique_papers": int(working["paper_id"].nunique()),
            "corruptions": events,
        },
    )
    return working
