from __future__ import annotations

import pandas as pd
import pytest

from core.utils import read_json
from ingestion import corruption
from ingestion.cleaning import refresh_derived_columns
from ingestion.corruption import corrupt_clean_dataframe
from observability import quality
from observability.quality import build_freshness_report, run_data_quality_checks

UNIQUE_ID = "expect_column_values_to_be_unique(paper_id)"
SUMMARY_LENGTH = "expect_column_value_lengths_to_be_between(summary)"
TITLE_LENGTH = "expect_column_value_lengths_to_be_between(title)"
SUMMARY_NOISE = "expect_column_values_to_not_match_regex(summary)"
SUITE_ORDER = [
    "expect_table_row_count_to_be_between",
    "expect_column_values_to_not_be_null(paper_id)",
    "expect_column_values_to_not_be_null(title)",
    "expect_column_values_to_not_be_null(text_for_embedding)",
    UNIQUE_ID,
    SUMMARY_LENGTH,
    TITLE_LENGTH,
    SUMMARY_NOISE,
]
SCENARIO_COUNTS = {
    "blank_summary": "BLANK_SUMMARY_ROWS",
    "inject_text_noise": "NOISE_ROWS",
    "truncate_title": "TRUNCATE_TITLE_ROWS",
    "stale_date": "STALE_DATE_ROWS",
    "duplicate_rows": "DUPLICATE_ROWS",
}


def _keys(report) -> list[str]:
    return [f"{item['expectation']}({item['column']})" if item["column"] else item["expectation"] for item in report["expectations"]]


def test_clean_table_passes_every_check(clean_df, settings):
    report = run_data_quality_checks(clean_df, settings, "baseline")

    assert report["success"] is True
    assert report["required_success"] is True
    assert report["gate_passed"] is True
    assert report["failed_expectations"] == []
    assert report["evaluated_expectations"] == report["successful_expectations"] == 8
    assert report["row_count"] == 24
    assert _keys(report) == SUITE_ORDER
    assert report["freshness"]["is_fresh"] is True
    assert report["freshness"]["stale_rows"] == 1  # one paper is 181 days old on the fixed run date
    assert read_json(settings.paths.baseline_quality_report) == report
    assert read_json(settings.paths.freshness_report) == report["freshness"]


def test_tiers_are_reported(clean_df, settings):
    report = run_data_quality_checks(clean_df, settings, "baseline")
    tiers = {key: item["tier"] for key, item in zip(_keys(report), report["expectations"], strict=True)}
    assert tiers[TITLE_LENGTH] == tiers[SUMMARY_NOISE] == "extra"
    assert tiers[UNIQUE_ID] == tiers[SUMMARY_LENGTH] == "required"


def test_other_report_names_get_their_own_files(clean_df, settings):
    run_data_quality_checks(clean_df, settings, "Repaired Run")
    assert (settings.paths.quality_dir / "repaired-run_quality_report.json").exists()
    assert (settings.paths.quality_dir / "repaired-run_freshness_report.json").exists()
    assert not settings.paths.baseline_quality_report.exists()


def test_full_corruption_fails_the_four_field_checks_and_freshness(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    report = run_data_quality_checks(corrupted, settings, "corrupted")

    assert report["success"] is False
    assert report["required_success"] is False
    assert report["gate_passed"] is False
    assert report["row_count"] == 24
    assert set(report["failed_expectations"]) == {UNIQUE_ID, TITLE_LENGTH, SUMMARY_LENGTH, SUMMARY_NOISE}
    assert report["freshness"]["is_fresh"] is False
    assert read_json(settings.paths.corrupted_quality_report) == report
    assert (settings.paths.quality_dir / "corrupted_freshness_report.json").exists()


@pytest.mark.parametrize(
    ("scenario", "expected_failures", "expect_fresh"),
    [
        ("blank_summary", [SUMMARY_LENGTH], True),
        ("inject_text_noise", [SUMMARY_NOISE], True),
        ("truncate_title", [TITLE_LENGTH], True),
        ("duplicate_rows", [UNIQUE_ID], True),
        ("stale_date", [], False),
        ("drop_latest_records", [], True),
    ],
)
def test_each_corruption_trips_only_its_own_check(clean_df, settings, monkeypatch, scenario, expected_failures, expect_fresh):
    """Run the real corruption code with every other scenario switched off.

    The latest-record drop cannot be switched off (it always drops at least one row); it trips
    nothing on its own, which is exactly the silent failure the lab is about.
    """
    for name, constant in SCENARIO_COUNTS.items():
        if name != scenario:
            monkeypatch.setattr(corruption, constant, 0)
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    report = run_data_quality_checks(corrupted, settings, f"only-{scenario}")

    assert report["failed_expectations"] == expected_failures
    assert report["freshness"]["is_fresh"] is expect_fresh
    only_extra_failed = all(key in {TITLE_LENGTH, SUMMARY_NOISE} for key in expected_failures)
    assert report["required_success"] is only_extra_failed


def test_blank_summary_as_empty_string_fails_length(clean_df, settings):
    blanked = clean_df.copy()
    blanked.loc[[0, 5], "summary"] = ""
    report = run_data_quality_checks(refresh_derived_columns(blanked), settings, "blank")
    assert report["failed_expectations"] == [SUMMARY_LENGTH]
    [summary_check] = [item for item in report["expectations"] if item["column"] == "summary" and "length" in item["expectation"]]
    assert summary_check["unexpected_count"] == 2


def test_summary_just_under_minimum_fails(clean_df, settings):
    shortened = clean_df.copy()
    shortened.loc[0, "summary"] = "x" * (quality.MIN_SUMMARY_CHARS - 1)
    shortened.loc[1, "summary"] = "y" * quality.MIN_SUMMARY_CHARS
    report = run_data_quality_checks(refresh_derived_columns(shortened), settings, "short")
    [summary_check] = [item for item in report["expectations"] if item["column"] == "summary" and "length" in item["expectation"]]
    assert summary_check["unexpected_count"] == 1


def test_null_paper_id_fails_not_null(clean_df, settings):
    broken = clean_df.copy()
    broken.loc[0, "paper_id"] = None
    report = run_data_quality_checks(broken, settings, "null-id")
    assert "expect_column_values_to_not_be_null(paper_id)" in report["failed_expectations"]
    assert report["required_success"] is False


def test_too_few_rows_fails_row_count(clean_df, settings):
    report = run_data_quality_checks(clean_df.head(quality.MIN_ROWS - 1), settings, "tiny")
    assert "expect_table_row_count_to_be_between" in report["failed_expectations"]


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Normal abstract, with (parentheses) and 95% accuracy.", False),
        ("Uses C++ & Rust; see [1].", False),
        ("Noise #@% inside", True),
        ("Noise {[]} inside", True),
        ("Two symbols ## only", False),
    ],
)
def test_junk_symbol_regex(text, flagged):
    import re

    assert bool(re.search(quality.JUNK_SYMBOL_RUN, text)) is flagged


# --- Freshness SLA threshold -------------------------------------------------------------------


def _ages_frame(ages: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"age_days": ages, "published": [f"2026-01-{index + 1:02d}" for index in range(len(ages))]})


def test_exactly_25_percent_stale_is_fresh(settings, tmp_path):
    report = build_freshness_report(_ages_frame([181] * 6 + [10] * 18), settings, tmp_path / "f.json")
    assert (report["stale_rows"], report["total_rows"], report["stale_ratio"]) == (6, 24, 0.25)
    assert report["is_fresh"] is True


def test_above_25_percent_stale_is_stale(settings, tmp_path):
    report = build_freshness_report(_ages_frame([181] * 7 + [10] * 17), settings, tmp_path / "f.json")
    assert report["stale_rows"] == 7
    assert report["is_fresh"] is False


def test_age_equal_to_threshold_is_not_stale(settings, tmp_path):
    threshold = settings.freshness_threshold_days
    report = build_freshness_report(_ages_frame([threshold] * 24), settings, tmp_path / "f.json")
    assert report["stale_rows"] == 0 and report["is_fresh"] is True


def test_freshness_report_fields(settings, tmp_path):
    path = tmp_path / "nested" / "f.json"
    report = build_freshness_report(_ages_frame([10, 20, 30, 200]), settings, path)
    assert report == {
        "latest_published": "2026-01-04",
        "oldest_published": "2026-01-01",
        "freshness_threshold_days": 180,
        "max_stale_ratio": 0.25,
        "stale_rows": 1,
        "total_rows": 4,
        "stale_ratio": 0.25,
        "median_age_days": 25.0,
        "is_fresh": True,
    }
    assert read_json(path) == report


def test_empty_table_is_never_fresh(settings, tmp_path):
    report = build_freshness_report(pd.DataFrame({"age_days": [], "published": []}), settings, tmp_path / "f.json")
    assert report["is_fresh"] is False
    assert report["stale_ratio"] == 1.0
    assert report["latest_published"] is None and report["median_age_days"] is None
