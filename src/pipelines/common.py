from __future__ import annotations

from datetime import date
import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import now_utc, read_json, write_csv, write_json
from ingestion.cleaning import CLEAN_COLUMNS


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy_logger in ("httpx", "chromadb", "sentence_transformers", "great_expectations", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def choose_run_date(settings: Settings) -> date:
    """RUN_DATE=YYYY-MM-DD pins the date (for reproducing a past run); otherwise today in UTC."""
    if settings.run_date:
        return date.fromisoformat(settings.run_date)
    return now_utc().date()


def load_run_context(settings: Settings) -> dict[str, Any]:
    if not settings.paths.run_context.exists():
        raise SystemExit("data/results/run_context.json is missing. Run `python script/run_phase1.py` first.")
    return read_json(settings.paths.run_context)


def table_sha256(df: pd.DataFrame) -> str:
    """Content hash of a clean table, used to prove that repair rebuilds exactly the baseline."""
    canonical = df[CLEAN_COLUMNS].reset_index(drop=True).to_json(orient="records", force_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_table(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    write_csv(df, csv_path)
    write_json(json_path, df.to_dict(orient="records"))


def read_table(json_path: Path) -> pd.DataFrame:
    # Built from the parsed records, not pd.read_json, so no column is re-typed on the way back in.
    return pd.DataFrame(read_json(json_path))[CLEAN_COLUMNS]


def relative(settings: Settings, path: Path) -> str:
    return path.resolve().relative_to(settings.paths.project_dir).as_posix()
