from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import safe_slug, write_json

# GX 1.x phones home on import unless told not to; the lab runs offline.
os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")
import great_expectations as gx  # noqa: E402

MIN_ROWS = 5
MAX_ROWS = 5000
MIN_SUMMARY_CHARS = 30
MIN_TITLE_CHARS = 10
MAX_STALE_RATIO = 0.25
# Three or more symbols in a row never appear in a real abstract, so they mark injected noise.
JUNK_SYMBOL_RUN = r"[#@$%^&*~|<>{}\[\]\\]{3,}"
GATE_COLUMNS = ["paper_id", "title", "summary", "text_for_embedding", "age_days"]


def _build_expectations() -> list[tuple[str, Any]]:
    """The four required expectations, then two extra checks for truncated titles and injected noise."""
    return [
        ("required", gx.expectations.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS)),
        ("required", gx.expectations.ExpectColumnValuesToNotBeNull(column="paper_id")),
        ("required", gx.expectations.ExpectColumnValuesToNotBeNull(column="title")),
        ("required", gx.expectations.ExpectColumnValuesToNotBeNull(column="text_for_embedding")),
        ("required", gx.expectations.ExpectColumnValuesToBeUnique(column="paper_id")),
        ("required", gx.expectations.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS)),
        ("extra", gx.expectations.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS)),
        ("extra", gx.expectations.ExpectColumnValuesToNotMatchRegex(column="summary", regex=JUNK_SYMBOL_RUN)),
    ]


def _silence_progress_bars(context) -> None:
    try:
        from great_expectations.data_context.types.base import ProgressBarsConfig

        context.variables.progress_bars = ProgressBarsConfig(globally=False, metric_calculations=False)
    except Exception:  # cosmetic only; validation works either way
        pass


def _quality_report_path(settings: Settings, report_name: str) -> Path:
    named_paths = {
        "baseline": settings.paths.baseline_quality_report,
        "corrupted": settings.paths.corrupted_quality_report,
    }
    return named_paths.get(report_name, settings.paths.quality_dir / f"{safe_slug(report_name)}_quality_report.json")


def _freshness_report_path(settings: Settings, report_name: str) -> Path:
    if report_name == "baseline":
        return settings.paths.freshness_report
    return settings.paths.quality_dir / f"{safe_slug(report_name)}_freshness_report.json"


def _expectation_key(expectation_type: str, column: str | None) -> str:
    return f"{expectation_type}({column})" if column else expectation_type


def _summarize_expectation(tier: str, expectation_result: dict[str, Any]) -> dict[str, Any]:
    config = expectation_result["expectation_config"]
    result = expectation_result.get("result", {})
    return {
        "tier": tier,
        "expectation": config["type"],
        "column": config.get("kwargs", {}).get("column"),
        "success": bool(expectation_result["success"]),
        "observed_value": result.get("observed_value"),
        "unexpected_count": result.get("unexpected_count"),
        "partial_unexpected_list": [str(value)[:80] for value in result.get("partial_unexpected_list", [])[:5]],
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Validate the table with Great Expectations 1.x and measure freshness.

    `success` covers the GX expectations only. Freshness is reported beside it, because a clean
    snapshot drifts stale as the calendar moves; `gate_passed` combines both for the pipeline.
    """
    context = gx.get_context(mode="ephemeral")
    _silence_progress_bars(context)
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": df[GATE_COLUMNS].copy()})

    tiered_expectations = _build_expectations()
    suite = context.suites.add(gx.ExpectationSuite(name=f"papers_{safe_slug(report_name)}_suite"))
    for _tier, expectation in tiered_expectations:
        suite.add_expectation(expectation)

    validation = batch.validate(suite, result_format="SUMMARY").to_json_dict()
    # GX does not return results in suite order, so match each result back by type and column.
    tier_by_key = {_expectation_key(expectation.expectation_type, getattr(expectation, "column", None)): tier for tier, expectation in tiered_expectations}
    order = list(tier_by_key)
    expectations = []
    for expectation_result in validation["results"]:
        config = expectation_result["expectation_config"]
        key = _expectation_key(config["type"], config.get("kwargs", {}).get("column"))
        expectations.append(_summarize_expectation(tier_by_key[key], expectation_result))
    expectations.sort(key=lambda item: order.index(_expectation_key(item["expectation"], item["column"])))
    freshness = build_freshness_report(df, settings, _freshness_report_path(settings, report_name))

    report = {
        "report_name": report_name,
        "engine": f"great_expectations {gx.__version__} (ephemeral context)",
        "success": bool(validation["success"]),
        "required_success": all(item["success"] for item in expectations if item["tier"] == "required"),
        "evaluated_expectations": len(expectations),
        "successful_expectations": sum(item["success"] for item in expectations),
        "failed_expectations": [_expectation_key(item["expectation"], item["column"]) for item in expectations if not item["success"]],
        "row_count": int(len(df)),
        "expectations": expectations,
        "freshness": freshness,
        "gate_passed": bool(validation["success"]) and freshness["is_fresh"],
    }
    write_json(_quality_report_path(settings, report_name), report)
    return report


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Freshness SLA: the data is stale when more than 25% of rows are older than the threshold."""
    threshold_days = settings.freshness_threshold_days
    total_rows = int(len(df))
    stale_rows = int((df["age_days"] > threshold_days).sum()) if total_rows else 0
    stale_ratio = stale_rows / total_rows if total_rows else 1.0
    published = df["published"].astype(str) if total_rows else pd.Series(dtype=str)
    payload = {
        "latest_published": published.max() if total_rows else None,
        "oldest_published": published.min() if total_rows else None,
        "freshness_threshold_days": threshold_days,
        "max_stale_ratio": MAX_STALE_RATIO,
        "stale_rows": stale_rows,
        "total_rows": total_rows,
        "stale_ratio": round(stale_ratio, 4),
        "median_age_days": float(df["age_days"].median()) if total_rows else None,
        "is_fresh": bool(total_rows and stale_ratio <= MAX_STALE_RATIO),
    }
    write_json(Path(report_path), payload)
    return payload
