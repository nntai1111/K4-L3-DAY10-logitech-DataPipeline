from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import great_expectations as gx
import pandas as pd

from core.config import Settings


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path: Path | str | None = None) -> dict[str, Any]:
    """Tong hop freshness report va ghi ra file JSON."""
    total_rows = len(df)
    if total_rows == 0:
        payload = {
            "latest_published": "",
            "oldest_published": "",
            "total_rows": 0,
            "stale_rows": 0,
            "stale_ratio": 0.0,
            "threshold_days": settings.freshness_threshold_days,
            "is_fresh": True,
        }
    else:
        pub_dates = pd.to_datetime(df["published"], errors="coerce")
        valid_dates = pub_dates.dropna()
        latest_published = str(valid_dates.max().date()) if not valid_dates.empty else ""
        oldest_published = str(valid_dates.min().date()) if not valid_dates.empty else ""

        threshold = settings.freshness_threshold_days
        stale_rows = int((df["age_days"] > threshold).sum()) if "age_days" in df.columns else 0
        stale_ratio = float(stale_rows / total_rows)
        is_fresh = bool(stale_ratio <= 0.25)

        payload = {
            "latest_published": latest_published,
            "oldest_published": oldest_published,
            "total_rows": total_rows,
            "stale_rows": stale_rows,
            "stale_ratio": round(stale_ratio, 4),
            "threshold_days": threshold,
            "is_fresh": is_fresh,
        }

    if report_path:
        out_path = Path(report_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Tao va chay bo Great Expectations 1.x data quality checks."""
    context = gx.get_context(mode="ephemeral")

    source_name = f"papers_source_{report_name}"
    asset_name = f"papers_asset_{report_name}"
    batch_def_name = f"papers_batch_{report_name}"
    suite_name = f"papers_suite_{report_name}"
    val_def_name = f"papers_val_def_{report_name}"

    data_source = context.data_sources.add_pandas(name=source_name)
    data_asset = data_source.add_dataframe_asset(name=asset_name)
    batch_def = data_asset.add_batch_definition_whole_dataframe(batch_def_name)

    suite = context.suites.add(gx.ExpectationSuite(name=suite_name))
    suite.add_expectation(gx.expectations.ExpectTableRowCountToBeBetween(min_value=5, max_value=5000))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="paper_id"))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="title"))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="text_for_embedding"))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeUnique(column="paper_id"))
    suite.add_expectation(gx.expectations.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30))

    validation_def = context.validation_definitions.add(
        gx.ValidationDefinition(
            name=val_def_name,
            data=batch_def,
            suite=suite,
        )
    )

    validation_result = validation_def.run(batch_parameters={"dataframe": df})
    success = bool(validation_result.success)

    freshness_path = settings.paths.quality_dir / f"{report_name}_freshness.json"
    freshness_info = build_freshness_report(df, settings, freshness_path)

    report_payload = {
        "success": success,
        "report_name": report_name,
        "total_records": len(df),
        "freshness": freshness_info,
        "gx_success": success,
    }

    report_out_path = settings.paths.quality_dir / f"{report_name}_quality_report.json"
    report_out_path.parent.mkdir(parents=True, exist_ok=True)
    report_out_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return report_payload

