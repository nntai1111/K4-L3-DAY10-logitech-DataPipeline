from __future__ import annotations

from datetime import date, timedelta
import random
import re

import pandas as pd
import pytest

from core.utils import first_sentence, read_json
from ingestion import corruption
from ingestion.corruption import corrupt_clean_dataframe
from observability.quality import JUNK_SYMBOL_RUN

FIELD_SCENARIOS = ("blank_summary", "inject_text_noise", "truncate_title", "stale_date")
SCENARIO_ORDER = ["drop_latest_records", *FIELD_SCENARIOS, "duplicate_rows"]


@pytest.fixture
def corrupted_run(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    log = read_json(settings.paths.corruption_log)
    by_name = {scenario["scenario"]: scenario for scenario in log["scenarios"]}
    return corrupted, log, by_name


def test_same_seed_gives_identical_output(clean_df, tmp_path):
    first = corrupt_clean_dataframe(clean_df, tmp_path / "a.json")
    second = corrupt_clean_dataframe(clean_df, tmp_path / "b.json")
    pd.testing.assert_frame_equal(first, second)
    assert read_json(tmp_path / "a.json") == read_json(tmp_path / "b.json")


def test_different_seed_picks_different_rows(clean_df, tmp_path):
    default = read_json_after(clean_df, tmp_path / "a.json", corruption.SEED)
    other = read_json_after(clean_df, tmp_path / "b.json", corruption.SEED + 1)
    assert default["seed"] == 42 and other["seed"] == 43
    assert [s["paper_ids"] for s in default["scenarios"][1:]] != [s["paper_ids"] for s in other["scenarios"][1:]]


def read_json_after(clean_df, path, seed):
    corrupt_clean_dataframe(clean_df, path, seed=seed)
    return read_json(path)


def test_input_table_is_not_modified(clean_df, tmp_path):
    before = clean_df.copy(deep=True)
    corrupt_clean_dataframe(clean_df, tmp_path / "log.json")
    pd.testing.assert_frame_equal(clean_df, before)


def test_row_count_is_preserved_at_24(corrupted_run):
    corrupted, log, by_name = corrupted_run
    assert len(corrupted) == 24
    assert (log["input_rows"], log["output_rows"]) == (24, 24)
    assert by_name["drop_latest_records"]["rows_affected"] == 4
    assert by_name["duplicate_rows"]["rows_affected"] == 4


def test_log_lists_six_scenarios_in_order(corrupted_run):
    _corrupted, log, _by_name = corrupted_run
    assert log["seed"] == corruption.SEED
    assert log["scenario_count"] == 6
    assert [scenario["scenario"] for scenario in log["scenarios"]] == SCENARIO_ORDER
    for scenario in log["scenarios"]:
        assert scenario["rows_affected"] == len(scenario["paper_ids"])
        assert scenario["description"]


def test_expected_row_counts_per_scenario(corrupted_run):
    _corrupted, _log, by_name = corrupted_run
    assert by_name["blank_summary"]["rows_affected"] == corruption.BLANK_SUMMARY_ROWS
    assert by_name["inject_text_noise"]["rows_affected"] == corruption.NOISE_ROWS
    assert by_name["truncate_title"]["rows_affected"] == corruption.TRUNCATE_TITLE_ROWS
    assert by_name["stale_date"]["rows_affected"] == corruption.STALE_DATE_ROWS


def test_drop_removes_the_four_latest_papers(clean_df, corrupted_run):
    corrupted, _log, by_name = corrupted_run
    latest = clean_df.sort_values(["published", "paper_id"], ascending=[False, True])["paper_id"].head(4).tolist()
    assert by_name["drop_latest_records"]["paper_ids"] == latest
    assert not set(latest) & set(corrupted["paper_id"])


def test_field_scenarios_target_disjoint_rows(corrupted_run):
    _corrupted, _log, by_name = corrupted_run
    dropped = set(by_name["drop_latest_records"]["paper_ids"])
    seen: set[str] = set()
    for name in FIELD_SCENARIOS:
        ids = set(by_name[name]["paper_ids"])
        assert len(ids) == by_name[name]["rows_affected"], f"{name} repeats a row"
        assert not ids & seen, f"{name} overlaps an earlier scenario"
        assert not ids & dropped, f"{name} touches a dropped row"
        seen |= ids


def test_duplicates_repeat_existing_ids(corrupted_run):
    corrupted, _log, by_name = corrupted_run
    counts = corrupted["paper_id"].value_counts()
    assert sorted(counts[counts > 1].index) == sorted(by_name["duplicate_rows"]["paper_ids"])
    assert counts.max() == 2


def test_blank_summary_rows_are_empty_strings(corrupted_run):
    corrupted, _log, by_name = corrupted_run
    rows = corrupted[corrupted["paper_id"].isin(by_name["blank_summary"]["paper_ids"])]
    assert (rows["summary"] == "").all()
    assert (rows["summary_chars"] == 0).all()


def test_truncated_titles_keep_seven_characters(clean_df, corrupted_run):
    corrupted, _log, by_name = corrupted_run
    original = clean_df.set_index("paper_id")["title"]
    for _, row in corrupted[corrupted["paper_id"].isin(by_name["truncate_title"]["paper_ids"])].iterrows():
        assert row["title"] == original[row["paper_id"]][: corruption.TRUNCATED_TITLE_CHARS]
        assert row["text_for_embedding"].startswith(f"Title: {row['title']}\n")


def test_stale_rows_shift_published_and_age_by_365(clean_df, corrupted_run, run_date):
    corrupted, _log, by_name = corrupted_run
    original = clean_df.set_index("paper_id")
    stale = corrupted[corrupted["paper_id"].isin(by_name["stale_date"]["paper_ids"])].drop_duplicates("paper_id")
    assert len(stale) == corruption.STALE_DATE_ROWS
    for _, row in stale.iterrows():
        before = original.loc[row["paper_id"]]
        assert row["published"] == (date.fromisoformat(before["published"]) - timedelta(days=365)).isoformat()
        assert row["age_days"] == before["age_days"] + corruption.STALE_SHIFT_DAYS
        # age_days stays consistent with the shifted date, as if the table had been rebuilt.
        assert row["age_days"] == (run_date - date.fromisoformat(row["published"])).days


def test_stale_rows_are_enough_to_breach_the_sla(clean_df, corrupted_run, settings):
    corrupted, _log, _by_name = corrupted_run
    stale_ratio = (corrupted["age_days"] > settings.freshness_threshold_days).mean()
    assert stale_ratio > 0.25


def test_noise_lands_inside_the_first_sentence(clean_df, corrupted_run):
    corrupted, _log, by_name = corrupted_run
    original = clean_df.set_index("paper_id")["summary"]
    noisy = corrupted[corrupted["paper_id"].isin(by_name["inject_text_noise"]["paper_ids"])].drop_duplicates("paper_id")
    assert len(noisy) == corruption.NOISE_ROWS
    for _, row in noisy.iterrows():
        opening = first_sentence(row["summary"])
        assert re.search(JUNK_SYMBOL_RUN, opening), f"no noise in the first sentence of {row['paper_id']}"
        assert opening != first_sentence(original[row["paper_id"]])
        assert row["summary_chars"] == len(row["summary"])


def test_untouched_rows_are_identical(clean_df, corrupted_run):
    corrupted, _log, by_name = corrupted_run
    touched = {paper_id for name in FIELD_SCENARIOS for paper_id in by_name[name]["paper_ids"]}
    untouched = corrupted[~corrupted["paper_id"].isin(touched)].drop_duplicates("paper_id").set_index("paper_id").sort_index()
    expected = clean_df.set_index("paper_id").loc[untouched.index]
    pd.testing.assert_frame_equal(untouched, expected)


def test_inject_noise_places_a_token_after_every_third_word():
    noisy = corruption._inject_noise("one two three four five six seven", random.Random(0))
    words = noisy.split()
    assert words[:3] == ["one", "two", "three"]
    assert words[3] in corruption.NOISE_TOKENS
    assert words[4:7] == ["four", "five", "six"]
    assert words[7] in corruption.NOISE_TOKENS
    assert words[8:] == ["seven"]


def test_shift_back():
    assert corruption._shift_back("2026-03-01", 365) == "2025-03-01"
