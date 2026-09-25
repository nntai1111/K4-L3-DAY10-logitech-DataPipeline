from __future__ import annotations

from collections import Counter
import json
import re

import pytest

from core.utils import first_sentence, read_json, write_json
from evaluation import testset
from retrieval.qa import _extract_answer

TYPE_FIELD = {"authors": "authors_joined", "date": "published", "categories": "categories_joined"}


@pytest.fixture
def samples(clean_df, settings):
    return testset.build_test_set(clean_df, settings.paths.eval_testset)


def test_ten_questions_with_the_required_mix(samples):
    assert len(samples) == testset.TEST_SET_SIZE == 10
    assert Counter(sample["question_type"] for sample in samples) == {"summary": 3, "authors": 3, "date": 2, "categories": 2}
    assert [sample["id"] for sample in samples] == [f"eval_{number:03d}" for number in range(1, 11)]
    assert [sample["question_type"] for sample in samples[:4]] == testset.QUESTION_TYPE_CYCLE


def test_file_is_written(samples, settings):
    assert read_json(settings.paths.eval_testset) == samples
    assert settings.paths.test_set_json == settings.paths.eval_testset


def test_each_question_points_at_one_distinct_known_paper(samples, clean_df):
    known = set(clean_df["paper_id"])
    doc_ids = [sample["ground_truth_doc_ids"] for sample in samples]
    assert all(len(ids) == 1 and ids[0] in known for ids in doc_ids)
    assert len({ids[0] for ids in doc_ids}) == 10


def test_questions_span_oldest_to_newest(samples, clean_df):
    by_id = clean_df.set_index("paper_id")["published"]
    dates = [by_id[sample["ground_truth_doc_ids"][0]] for sample in samples]
    assert dates == sorted(dates)
    assert dates[0] == clean_df["published"].min()
    assert dates[-1] == clean_df["published"].max()


def test_ground_truth_uses_the_stored_string_form(samples, clean_df):
    rows = clean_df.set_index("paper_id")
    for sample in samples:
        row = rows.loc[sample["ground_truth_doc_ids"][0]]
        if sample["question_type"] == "summary":
            assert sample["ground_truth"] == first_sentence(row["summary"])
        else:
            assert sample["ground_truth"] == row[TYPE_FIELD[sample["question_type"]]]


def test_quoted_title_resolves_to_the_target_paper(samples, clean_df):
    titles = clean_df.set_index("paper_id")["title"]
    for sample in samples:
        match = re.search(r"'([^']+)'", sample["question"])
        assert match, sample["question"]
        assert match.group(1) == titles[sample["ground_truth_doc_ids"][0]]


def test_every_question_routes_to_the_right_field(samples, clean_df, make_search_result):
    """The answerer picks its field from the question wording; each template must hit the right one."""
    rows = clean_df.set_index("paper_id", drop=False)
    for sample in samples:
        row = rows.loc[sample["ground_truth_doc_ids"][0]].to_dict()
        answer = _extract_answer(sample["question"], make_search_result(row))
        assert answer == sample["ground_truth"], f"{sample['id']} ({sample['question_type']}) routed to the wrong field"


def test_titles_with_single_quotes_are_skipped(clean_df, tmp_path):
    quoted = clean_df.copy()
    quoted.loc[:, "title"] = [f"It's paper {index}" if index < 5 else title for index, title in enumerate(quoted["title"])]
    samples = testset.build_test_set(quoted, tmp_path / "t.json")
    assert all("It's" not in sample["question"] for sample in samples)


def test_duplicate_rows_do_not_count_twice(clean_df, tmp_path):
    import pandas as pd

    doubled = pd.concat([clean_df, clean_df], ignore_index=True)
    samples = testset.build_test_set(doubled, tmp_path / "t.json")
    assert len({sample["ground_truth_doc_ids"][0] for sample in samples}) == 10


def test_too_few_usable_papers_raises(clean_df, tmp_path):
    with pytest.raises(ValueError, match="at least 10"):
        testset.build_test_set(clean_df.head(9), tmp_path / "t.json")
    assert not (tmp_path / "t.json").exists()


def test_build_is_deterministic(clean_df, tmp_path):
    first = testset.build_test_set(clean_df, tmp_path / "a.json")
    second = testset.build_test_set(clean_df.sample(frac=1, random_state=1), tmp_path / "b.json")
    assert first == second


@pytest.mark.parametrize(("total", "count", "expected"), [(24, 1, [0]), (10, 10, list(range(10))), (3, 2, [0, 2])])
def test_spread_positions(total, count, expected):
    assert testset._spread_positions(total, count) == expected


def test_spread_positions_for_the_snapshot_are_distinct():
    positions = testset._spread_positions(24, 10)
    assert len(positions) == 10 and positions[0] == 0 and positions[-1] == 23


# --- load_or_create_test_set -------------------------------------------------------------------


def test_load_or_create_builds_when_missing(clean_df, settings):
    loaded = testset.load_or_create_test_set(clean_df, settings.paths.eval_testset)
    assert len(loaded.samples) == 10
    assert settings.paths.eval_testset.exists()


def test_load_or_create_reuses_a_matching_frozen_file(clean_df, settings, samples):
    frozen = [dict(sample, question=sample["question"] + " [frozen]") for sample in samples]
    write_json(settings.paths.eval_testset, frozen)
    loaded = testset.load_or_create_test_set(clean_df, settings.paths.eval_testset)
    assert loaded.samples == frozen


def test_load_or_create_rebuilds_on_refresh(clean_df, settings, samples):
    write_json(settings.paths.eval_testset, [dict(samples[0], question="stale")])
    loaded = testset.load_or_create_test_set(clean_df, settings.paths.eval_testset, refresh=True)
    assert loaded.samples == samples


@pytest.mark.parametrize("frozen", [[], [{"ground_truth_doc_ids": ["10.9999/unknown"]}]], ids=["empty", "unknown-doc"])
def test_load_or_create_rebuilds_when_file_no_longer_matches(clean_df, settings, samples, frozen):
    settings.paths.eval_testset.write_text(json.dumps(frozen), encoding="utf-8")
    loaded = testset.load_or_create_test_set(clean_df, settings.paths.eval_testset)
    assert loaded.samples == samples
