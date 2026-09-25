from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, read_json, write_json

QUESTION_TYPES = ("summary", "authors", "date", "categories")
DEFAULT_SAMPLE_SIZE = 10
REQUIRED_COLUMNS = {"paper_id", "title", "summary", "authors_joined", "categories_joined", "published"}

# Phrasings are aligned with retrieval.qa._extract_answer: the quoted title triggers the exact lookup and
# the keywords ("who authored", "when was", "what categories") select the answer field.
QUESTION_TEMPLATES = {
    "summary": "What is the main finding of the paper '{title}'?",
    "authors": "Who authored the paper '{title}'?",
    "date": "When was the paper '{title}' published?",
    "categories": "What categories does the paper '{title}' belong to?",
}


def _ground_truth(row: pd.Series, question_type: str) -> str:
    if question_type == "summary":
        return first_sentence(row["summary"])
    if question_type == "authors":
        return row["authors_joined"]
    if question_type == "date":
        return row["published"]
    return row["categories_joined"]


def _spread_positions(total: int, count: int) -> list[int]:
    """Evenly spaced row positions so the questions cover the whole publication-date range."""
    if total >= count:
        if count == 1:
            return [0]
        return [round(index * (total - 1) / (count - 1)) for index in range(count)]
    return [index % total for index in range(count)]


def build_test_set(df: pd.DataFrame, output_path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> list[dict[str, Any]]:
    """Build a fixed benchmark over the four question types and write it to `output_path`."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Clean dataframe is missing columns required for the test set: {sorted(missing)}")

    documents = df.drop_duplicates(subset="paper_id")
    # An apostrophe inside the title would break the quoted-title lookup in retrieval.qa.
    documents = documents[
        ~documents["title"].str.contains("'", regex=False)
        & documents["summary"].str.len().gt(0)
        & documents["authors_joined"].str.len().gt(0)
    ]
    documents = documents.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    if len(documents) < len(QUESTION_TYPES):
        raise ValueError(
            f"Need at least {len(QUESTION_TYPES)} usable documents to cover every question type, got {len(documents)}."
        )

    test_set: list[dict[str, Any]] = []
    for index, position in enumerate(_spread_positions(len(documents), sample_size)):
        row = documents.iloc[position]
        question_type = QUESTION_TYPES[index % len(QUESTION_TYPES)]
        test_set.append(
            {
                "id": f"eval_{index + 1:03d}",
                "question_type": question_type,
                "question": QUESTION_TEMPLATES[question_type].format(title=row["title"]),
                "ground_truth": _ground_truth(row, question_type),
                "ground_truth_doc_ids": [row["paper_id"]],
            }
        )

    write_json(Path(output_path), test_set)
    return test_set


def load_or_build_test_set(df: pd.DataFrame, output_path, refresh: bool = False) -> tuple[list[dict[str, Any]], bool]:
    """Reuse the existing benchmark so every state is scored on the same questions.

    The file is rebuilt only when asked (`REFRESH_TEST_SET=1`), when it is missing, or when it
    references papers that are no longer in the dataset. Returns (test_set, was_rebuilt).
    """
    path = Path(output_path)
    if path.exists() and not refresh:
        test_set = read_json(path)
        known_ids = set(df["paper_id"])
        if test_set and all(set(item.get("ground_truth_doc_ids", [])) <= known_ids for item in test_set):
            return test_set, False
    return build_test_set(df, path), True
