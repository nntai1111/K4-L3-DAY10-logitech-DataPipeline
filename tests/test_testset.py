from __future__ import annotations

from collections import Counter

import pytest

from core.utils import read_json
from evaluation.testset import build_test_set, load_or_build_test_set
from retrieval.index import SearchResult
from retrieval.qa import _extract_answer

REQUIRED_KEYS = {"id", "question_type", "question", "ground_truth", "ground_truth_doc_ids"}


def test_test_set_structure(clean_df, tmp_path):
    path = tmp_path / "test_set.json"
    test_set = build_test_set(clean_df, path)
    assert len(test_set) == 10
    assert [item["id"] for item in test_set] == [f"eval_{index:03d}" for index in range(1, 11)]
    assert all(set(item) == REQUIRED_KEYS for item in test_set)
    assert Counter(item["question_type"] for item in test_set) == {"summary": 3, "authors": 3, "date": 2, "categories": 2}
    assert len({item["ground_truth_doc_ids"][0] for item in test_set}) == 10
    assert read_json(path) == test_set


def test_questions_select_the_matching_answer_field_in_qa(clean_df, tmp_path):
    """Every question must route to the field its ground truth was built from (see retrieval.qa)."""
    rows = clean_df.set_index("paper_id")
    for item in build_test_set(clean_df, tmp_path / "t.json"):
        row = rows.loc[item["ground_truth_doc_ids"][0]]
        assert f"'{row['title']}'" in item["question"]
        metadata = {
            "authors_joined": row["authors_joined"],
            "published": row["published"],
            "categories_joined": row["categories_joined"],
            "summary": row["summary"],
        }
        result = SearchResult(paper_id=row.name, title=row["title"], score=1.0, content="", metadata=metadata)
        assert _extract_answer(item["question"], result) == item["ground_truth"]


def test_small_corpus_reuses_papers_with_different_question_types(clean_df, tmp_path):
    test_set = build_test_set(clean_df.head(5), tmp_path / "t.json")
    assert len(test_set) == 10
    pairs = {(item["ground_truth_doc_ids"][0], item["question_type"]) for item in test_set}
    assert len(pairs) == 10


def test_invalid_inputs_are_rejected(clean_df, tmp_path):
    with pytest.raises(ValueError, match="at least 4"):
        build_test_set(clean_df.head(3), tmp_path / "t.json")
    with pytest.raises(ValueError, match="missing columns"):
        build_test_set(clean_df.drop(columns=["authors_joined"]), tmp_path / "t.json")


def test_titles_with_apostrophes_are_skipped(clean_df, tmp_path):
    df = clean_df.copy()
    df.loc[0, "title"] = "Don't Break The Quoted Lookup"
    test_set = build_test_set(df, tmp_path / "t.json")
    assert df.loc[0, "paper_id"] not in {item["ground_truth_doc_ids"][0] for item in test_set}


def test_load_or_build_keeps_the_benchmark_fixed(clean_df, tmp_path):
    path = tmp_path / "t.json"
    first, rebuilt = load_or_build_test_set(clean_df, path)
    assert rebuilt is True
    again, rebuilt = load_or_build_test_set(clean_df.iloc[::-1], path)
    assert (again, rebuilt) == (first, False)
    _, rebuilt = load_or_build_test_set(clean_df, path, refresh=True)
    assert rebuilt is True
    missing_paper = clean_df[clean_df["paper_id"] != first[0]["ground_truth_doc_ids"][0]]
    _, rebuilt = load_or_build_test_set(missing_paper, path)
    assert rebuilt is True
