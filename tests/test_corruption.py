from __future__ import annotations

import random
import re

import pandas as pd

from core.utils import read_json
from ingestion.corruption import (
    STALE_SHIFT_DAYS,
    TRUNCATED_TITLE_CHARS,
    _inject_noise,
    _RowPicker,
    corrupt_clean_dataframe,
)
from observability.quality import NOISE_REGEX

EXPECTED_TYPES = ["drop_latest_records", "blank_summary", "inject_noise", "truncate_title", "stale_date", "duplicate_rows"]


def _run(clean_df, tmp_path, seed=42):
    log_path = tmp_path / f"log_{seed}.json"
    corrupted = corrupt_clean_dataframe(clean_df, log_path, seed=seed)
    return corrupted, read_json(log_path)


def test_corruption_is_deterministic_and_logs_six_scenarios(clean_df, tmp_path):
    first, log = _run(clean_df, tmp_path)
    second, _ = _run(clean_df, tmp_path)
    pd.testing.assert_frame_equal(first, second)
    assert [event["type"] for event in log["corruptions"]] == EXPECTED_TYPES
    assert all(event["affected_rows"] > 0 and event["detected_by"] for event in log["corruptions"])
    duplicates = log["corruptions"][-1]["affected_rows"]
    assert log["input_rows"] == 24
    assert log["output_rows"] == 24 - 5 + duplicates == len(first)
    assert log["unique_papers"] == 19


def test_each_scenario_changes_the_data_as_logged(clean_df, tmp_path):
    corrupted, log = _run(clean_df, tmp_path)
    events = {event["type"]: event for event in log["corruptions"]}
    original = clean_df.set_index("paper_id")
    by_id = corrupted.drop_duplicates("paper_id").set_index("paper_id")

    newest_five = clean_df.sort_values("published", ascending=False)["paper_id"].head(5)
    assert set(events["drop_latest_records"]["paper_ids"]) == set(newest_five)
    assert not set(newest_five) & set(corrupted["paper_id"])

    for paper_id in events["blank_summary"]["paper_ids"]:
        assert by_id.loc[paper_id, "summary"] == ""
        assert by_id.loc[paper_id, "text_for_embedding"].endswith("Summary: ")
    for paper_id in events["inject_noise"]["paper_ids"]:
        assert re.search(NOISE_REGEX, by_id.loc[paper_id, "summary"])
    for paper_id in events["truncate_title"]["paper_ids"]:
        title = by_id.loc[paper_id, "title"]
        assert len(title) <= TRUNCATED_TITLE_CHARS < 8
        assert original.loc[paper_id, "title"].startswith(title)
    for paper_id in events["stale_date"]["paper_ids"]:
        shifted = pd.Timestamp(original.loc[paper_id, "published"]) - pd.Timedelta(days=STALE_SHIFT_DAYS)
        assert by_id.loc[paper_id, "published"] == shifted.strftime("%Y-%m-%d")
        assert by_id.loc[paper_id, "age_days"] == original.loc[paper_id, "age_days"] + STALE_SHIFT_DAYS

    counts = corrupted["paper_id"].value_counts()
    assert all(counts[paper_id] == 2 for paper_id in events["duplicate_rows"]["paper_ids"])

    touched = [set(events[kind]["paper_ids"]) for kind in ("blank_summary", "inject_noise", "truncate_title", "stale_date")]
    assert sum(len(ids) for ids in touched) == len(set().union(*touched))  # scenarios 2-5 hit distinct papers


def test_seed_controls_which_rows_are_hit(clean_df, tmp_path):
    _, log_a = _run(clean_df, tmp_path, seed=1)
    _, log_b = _run(clean_df, tmp_path, seed=2)
    assert log_a["corruptions"][1]["paper_ids"] != log_b["corruptions"][1]["paper_ids"]
    assert log_a["corruptions"][0]["paper_ids"] == log_b["corruptions"][0]["paper_ids"]  # newest rows do not depend on seed


def test_row_picker_recycles_rows_when_the_pool_runs_out():
    picker = _RowPicker(range(3), random.Random(0))
    first = picker.take(2)
    second = picker.take(2)
    assert len(set(first)) == 2 and len(set(second)) == 2
    assert set(first) | set(second) == {0, 1, 2}


def test_noise_injection_always_hits_the_first_sentence():
    rng = random.Random(3)
    noisy = _inject_noise("First sentence here. Second one.", rng)
    assert re.search(NOISE_REGEX, noisy.split(".")[0])
    assert re.search(NOISE_REGEX, _inject_noise("", rng))
