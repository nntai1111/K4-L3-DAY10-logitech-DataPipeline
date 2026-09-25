from __future__ import annotations

import pandas as pd
import pytest

from core.utils import read_json
from observability.quality import (
    build_freshness_report,
    compute_freshness,
    freshness_report_path,
    quality_report_path,
    run_data_quality_checks,
)

REQUIRED_TYPES = {
    "expect_table_row_count_to_be_between",
    "expect_column_values_to_not_be_null",
    "expect_column_values_to_be_unique",
    "expect_column_value_lengths_to_be_between",
}


def test_clean_snapshot_passes_the_gx_gate(settings, clean_df):
    report = run_data_quality_checks(clean_df, settings, "baseline")
    assert report["success"] is True
    assert report["failed_checks"] == []
    assert report["statistics"]["evaluated_expectations"] == 12
    assert REQUIRED_TYPES <= {entry["expectation"] for entry in report["expectations"]}
    assert {entry["check_id"] for entry in report["expectations"] if entry["required"]} == {
        "row_count",
        "paper_id_not_null",
        "title_not_null",
        "text_for_embedding_not_null",
        "paper_id_unique",
        "summary_min_length",
    }
    assert read_json(settings.paths.baseline_quality_report)["success"] is True
    assert report["gx_validation_result"] == "data/quality/gx/baseline_validation_result.json"
    assert (settings.paths.gx_dir / "baseline_validation_result.json").exists()


def _duplicate(df):
    return pd.concat([df, df.head(2)], ignore_index=True)


def _set(column, value, rows=(0, 1)):
    def mutate(df):
        df = df.copy()
        for row in rows:
            df.loc[row, column] = value
        return df

    return mutate


@pytest.mark.parametrize(
    ("mutate", "expected_failure"),
    [
        (_duplicate, "paper_id_unique"),
        (_set("summary", ""), "summary_min_length"),
        (_set("summary", "Useful text #@$x9Q with noise"), "summary_no_noise"),
        (_set("title", "Agentic"), "title_min_length"),
        (_set("title", None), "title_not_null"),
        (_set("paper_id", "not-a-doi"), "paper_id_is_doi"),
        (_set("published", "22/07/2026"), "published_iso_date"),
        (lambda df: df.iloc[3:], "source_papers_present"),
        (lambda df: df.head(3), "row_count"),
        (lambda df: df.drop(columns=["comment"]), "schema_columns"),
    ],
)
def test_each_defect_trips_its_dedicated_check(settings, clean_df, mutate, expected_failure):
    report = run_data_quality_checks(mutate(clean_df), settings, "corrupted")
    assert report["success"] is False
    assert expected_failure in report["failed_checks"]
    failed = next(entry for entry in report["expectations"] if entry["check_id"] == expected_failure)
    assert failed["success"] is False


def test_missing_source_ids_are_reported(settings, clean_df):
    report = run_data_quality_checks(clean_df.iloc[2:], settings, "corrupted")
    entry = next(entry for entry in report["expectations"] if entry["check_id"] == "source_papers_present")
    assert entry["missing_count"] == 2
    assert entry["observed_value"] == "22/24 source papers present"
    assert set(entry["missing_examples"]) == set(clean_df["paper_id"].iloc[:2])


def test_gate_without_raw_snapshot_skips_source_reconciliation(settings, clean_df):
    settings.paths.raw_records_json.unlink()
    report = run_data_quality_checks(clean_df, settings, "adhoc check")
    assert report["success"] is True
    assert "source_papers_present" not in {entry["check_id"] for entry in report["expectations"]}
    assert (settings.paths.quality_dir / "adhoc-check_quality_report.json").exists()


def test_freshness_sla_boundaries(settings, clean_df):
    fresh = compute_freshness(clean_df, settings)
    assert (fresh["stale_rows"], fresh["total_rows"], fresh["is_fresh"]) == (1, 24, True)
    assert fresh["latest_published"] == "2026-07-22"
    assert fresh["newest_age_days"] == 65

    # The snapshot already holds one stale paper (181 days), so +5 rows = 6/24 = exactly 25%.
    at_limit = clean_df.copy()
    at_limit.loc[:4, "age_days"] = 400
    assert compute_freshness(at_limit, settings)["is_fresh"] is True

    stale = clean_df.copy()
    stale.loc[:5, "age_days"] = 400  # 7/24 = 29%
    report = build_freshness_report(stale, settings, freshness_report_path(settings, "corrupted"))
    assert report["is_fresh"] is False
    assert report["status"] == "STALE"
    assert report["message"].startswith("ALERT")
    assert read_json(settings.paths.quality_dir / "corrupted_freshness_report.json")["stale_rows"] == 7


def test_freshness_without_known_ages_is_not_reported_fresh(settings):
    empty = compute_freshness(pd.DataFrame(columns=["paper_id", "published", "age_days"]), settings)
    assert (empty["is_fresh"], empty["status"], empty["latest_published"]) == (False, "UNKNOWN", None)
    no_ages = compute_freshness(pd.DataFrame({"paper_id": ["a", "b"]}), settings)
    assert (no_ages["is_fresh"], no_ages["status"], no_ages["newest_age_days"]) == (False, "UNKNOWN", None)


def test_report_paths(settings):
    paths = settings.paths
    assert quality_report_path(settings, "baseline") == paths.baseline_quality_report
    assert quality_report_path(settings, "corrupted") == paths.corrupted_quality_report
    assert quality_report_path(settings, "repaired") == paths.quality_dir / "repaired_quality_report.json"
    assert freshness_report_path(settings, "baseline") == paths.freshness_report
    assert freshness_report_path(settings, "repaired") == paths.quality_dir / "repaired_freshness_report.json"
