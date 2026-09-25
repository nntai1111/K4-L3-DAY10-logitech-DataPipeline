from __future__ import annotations

from pathlib import Path
from typing import Any

import great_expectations as gx
from great_expectations.data_context.types.base import ProgressBarsConfig
import great_expectations.expectations as gxe
import pandas as pd

from core.config import Settings
from core.utils import now_utc, project_relative, safe_slug, write_json
from ingestion.cleaning import CLEAN_COLUMNS, LIST_COLUMNS, MIN_SUMMARY_CHARS, MIN_TITLE_CHARS, build_clean_dataframe
from ingestion.crossref import load_raw_records

MIN_ROWS = 5
MAX_ROWS = 5000
MAX_STALE_RATIO = 0.25
NOT_NULL_COLUMNS = ("paper_id", "title", "text_for_embedding")
NOISE_REGEX = r"[#@$%^&*~|]{2,}"
DOI_REGEX = r"^10\.\d{4,9}/\S+$"
ISO_DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"
MAX_EXAMPLES = 5


def _build_checks(expected_ids: list[str] | None) -> list[dict[str, Any]]:
    """Each check = one GX 1.x expectation plus the metadata used by the reports.

    `required` marks the four expectation types mandated by the lab; the others extend the gate so
    that every corruption scenario has a dedicated detector.
    """
    checks: list[dict[str, Any]] = [
        {
            "check_id": "schema_columns",
            "dimension": "schema",
            "required": False,
            "description": "Dataset exposes every column of the clean schema",
            "expectation": gxe.ExpectTableColumnsToMatchSet(column_set=CLEAN_COLUMNS, exact_match=False),
        },
        {
            "check_id": "row_count",
            "dimension": "volume",
            "required": True,
            "description": f"Row count between {MIN_ROWS} and {MAX_ROWS}",
            "expectation": gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS),
        },
    ]
    for column in NOT_NULL_COLUMNS:
        checks.append(
            {
                "check_id": f"{column}_not_null",
                "dimension": "completeness",
                "required": True,
                "description": f"{column} is never null",
                "expectation": gxe.ExpectColumnValuesToNotBeNull(column=column),
            }
        )
    checks += [
        {
            "check_id": "paper_id_unique",
            "dimension": "uniqueness",
            "required": True,
            "description": "paper_id is unique (no duplicate documents)",
            "expectation": gxe.ExpectColumnValuesToBeUnique(column="paper_id"),
        },
        {
            "check_id": "summary_min_length",
            "dimension": "validity",
            "required": True,
            "description": f"summary has at least {MIN_SUMMARY_CHARS} characters",
            "expectation": gxe.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS),
        },
        {
            "check_id": "title_min_length",
            "dimension": "validity",
            "required": False,
            "description": f"title has at least {MIN_TITLE_CHARS} characters (detects truncation)",
            "expectation": gxe.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS),
        },
        {
            "check_id": "summary_no_noise",
            "dimension": "validity",
            "required": False,
            "description": "summary contains no runs of garbage symbols (detects injected noise)",
            "expectation": gxe.ExpectColumnValuesToNotMatchRegex(column="summary", regex=NOISE_REGEX),
        },
        {
            "check_id": "paper_id_is_doi",
            "dimension": "validity",
            "required": False,
            "description": "paper_id looks like a DOI (10.xxxx/...)",
            "expectation": gxe.ExpectColumnValuesToMatchRegex(column="paper_id", regex=DOI_REGEX),
        },
        {
            "check_id": "published_iso_date",
            "dimension": "validity",
            "required": False,
            "description": "published is an ISO date (YYYY-MM-DD)",
            "expectation": gxe.ExpectColumnValuesToMatchRegex(column="published", regex=ISO_DATE_REGEX),
        },
    ]
    if expected_ids:
        checks.append(
            {
                "check_id": "source_papers_present",
                "dimension": "completeness",
                "required": False,
                "description": "Every paper from the raw source snapshot is present (detects dropped records)",
                "expectation": gxe.ExpectColumnDistinctValuesToContainSet(column="paper_id", value_set=expected_ids),
            }
        )
    for check in checks:
        check["expectation"].meta = {"check_id": check["check_id"]}
    return checks


def _expected_source_ids(settings: Settings) -> list[str] | None:
    """paper_ids the dataset must contain: the raw snapshot passed through the cleaning rules."""
    path = settings.paths.raw_records_json
    if not path.exists():
        return None
    try:
        source_df = build_clean_dataframe(load_raw_records(path), now_utc())
    except (OSError, ValueError, KeyError):
        return None
    return sorted(source_df["paper_id"].unique().tolist())


def _validation_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    for column in LIST_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].map(lambda values: "; ".join(values) if isinstance(values, list) else values)
    return frame


def _run_gx_suite(df: pd.DataFrame, checks: list[dict[str, Any]], suite_name: str):
    context = gx.get_context(mode="ephemeral")
    context.variables.progress_bars = ProgressBarsConfig(globally=False)
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": _validation_frame(df)})

    suite = context.suites.add(gx.ExpectationSuite(name=suite_name))
    for check in checks:
        suite.add_expectation(check["expectation"])
    return batch.validate(suite, result_format="SUMMARY")


def _summarize_result(item: dict[str, Any], check: dict[str, Any], expected_ids: list[str] | None) -> dict[str, Any]:
    config = item.get("expectation_config") or {}
    result = item.get("result") or {}
    exception = item.get("exception_info") or {}
    summary: dict[str, Any] = {
        "check_id": check.get("check_id"),
        "expectation": config.get("type"),
        "column": (config.get("kwargs") or {}).get("column"),
        "dimension": check.get("dimension"),
        "required": check.get("required", False),
        "description": check.get("description"),
        "success": bool(item.get("success")),
    }
    if "unexpected_count" in result:
        summary["element_count"] = result.get("element_count")
        summary["unexpected_count"] = result.get("unexpected_count")
        summary["unexpected_percent"] = result.get("unexpected_percent")
        summary["unexpected_examples"] = (result.get("partial_unexpected_list") or [])[:MAX_EXAMPLES]
    if check.get("check_id") == "source_papers_present":
        expected = len(expected_ids or [])
        missing_count = int(result.get("missing_count") or 0)
        summary["observed_value"] = f"{expected - missing_count}/{expected} source papers present"
        summary["missing_count"] = missing_count
        summary["missing_examples"] = (result.get("partial_missing_list") or [])[:MAX_EXAMPLES]
    elif "observed_value" in result:
        summary["observed_value"] = result.get("observed_value")
    if exception.get("raised_exception"):
        summary["exception"] = exception.get("exception_message")
    return summary


def quality_report_path(settings: Settings, report_name: str) -> Path:
    known = {
        "baseline": settings.paths.baseline_quality_report,
        "corrupted": settings.paths.corrupted_quality_report,
    }
    return known.get(report_name, settings.paths.quality_dir / f"{safe_slug(report_name)}_quality_report.json")


def freshness_report_path(settings: Settings, state: str) -> Path:
    if state == "baseline":
        return settings.paths.freshness_report
    return settings.paths.quality_dir / f"{safe_slug(state)}_freshness_report.json"


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Validate the dataset with a Great Expectations 1.x suite and write the report to data/quality/."""
    expected_ids = _expected_source_ids(settings)
    checks = _build_checks(expected_ids)
    validation = _run_gx_suite(df, checks, suite_name=f"papers_quality_{safe_slug(report_name)}")
    raw_result = validation.to_json_dict()

    gx_result_path = settings.paths.gx_dir / f"{safe_slug(report_name)}_validation_result.json"
    write_json(gx_result_path, raw_result)

    checks_by_id = {check["check_id"]: check for check in checks}
    order = {check["check_id"]: position for position, check in enumerate(checks)}
    expectations = []
    for item in raw_result.get("results", []):
        check_id = ((item.get("expectation_config") or {}).get("meta") or {}).get("check_id")
        expectations.append(_summarize_result(item, checks_by_id.get(check_id, {}), expected_ids))
    expectations.sort(key=lambda entry: order.get(entry["check_id"], len(order)))

    failed = [entry for entry in expectations if not entry["success"]]
    report = {
        "report_name": report_name,
        "engine": f"great_expectations {gx.__version__} (ephemeral context, pandas dataframe batch)",
        "checked_at": now_utc().isoformat(),
        "row_count": int(len(df)),
        "unique_paper_ids": int(df["paper_id"].nunique()) if "paper_id" in df.columns else 0,
        "success": bool(raw_result.get("success")),
        "required_checks_success": all(entry["success"] for entry in expectations if entry["required"]),
        "statistics": raw_result.get("statistics", {}),
        "failed_checks": [entry["check_id"] for entry in failed],
        "expectations": expectations,
        "freshness": compute_freshness(df, settings),
        "gx_validation_result": project_relative(gx_result_path, settings.paths.project_dir),
    }
    write_json(quality_report_path(settings, report_name), report)
    return report


def _int_or_none(value: Any) -> int | None:
    return None if pd.isna(value) else int(value)


def compute_freshness(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    """Freshness SLA: data is stale when more than 25% of rows are older than the threshold."""
    total = int(len(df))
    missing = pd.Series(float("nan"), index=df.index)
    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df.columns else missing
    published = pd.to_datetime(df["published"] if "published" in df.columns else missing, errors="coerce", format="ISO8601")
    stale_mask = ages > settings.freshness_threshold_days
    stale_rows = int(stale_mask.sum())
    stale_ratio = stale_rows / total if total else 1.0
    # Without any known age the SLA cannot be verified, so the data is not reported as fresh.
    known_ages = int(ages.notna().sum())
    is_fresh = bool(known_ages > 0 and stale_ratio <= MAX_STALE_RATIO)
    stale_ids = df.loc[stale_mask, "paper_id"].unique().tolist() if "paper_id" in df.columns else []
    return {
        "threshold_days": settings.freshness_threshold_days,
        "max_stale_ratio": MAX_STALE_RATIO,
        "total_rows": total,
        "stale_rows": stale_rows,
        "stale_ratio": round(stale_ratio, 4),
        "latest_published": published.max().date().isoformat() if published.notna().any() else None,
        "oldest_published": published.min().date().isoformat() if published.notna().any() else None,
        "newest_age_days": _int_or_none(ages.min()),
        "median_age_days": float(ages.median()) if ages.notna().any() else None,
        "oldest_age_days": _int_or_none(ages.max()),
        "stale_paper_ids": sorted(stale_ids),
        "is_fresh": is_fresh,
        "status": "FRESH" if is_fresh else ("STALE" if known_ages else "UNKNOWN"),
    }


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Summarize dataset freshness against the SLA and write it as JSON."""
    freshness = compute_freshness(df, settings)
    share = f"{freshness['stale_rows']}/{freshness['total_rows']} rows ({freshness['stale_ratio']:.1%})"
    limit = f"{freshness['threshold_days']} days"
    if freshness["is_fresh"]:
        message = f"OK: {share} are older than {limit}, within the {MAX_STALE_RATIO:.0%} SLA."
    elif freshness["status"] == "UNKNOWN":
        message = "UNKNOWN: no row has a usable age_days value, so the freshness SLA cannot be verified."
    else:
        message = f"ALERT: {share} are older than {limit}, above the {MAX_STALE_RATIO:.0%} SLA. Refresh the source."
    report = {"checked_at": now_utc().isoformat(), **freshness, "message": message}
    write_json(Path(report_path), report)
    return report
