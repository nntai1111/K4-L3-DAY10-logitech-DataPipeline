from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, read_json, write_json

TEST_SET_SIZE = 10
# 3 summary, 3 authors, 2 date, 2 categories, interleaved so every part of the date range gets each type.
QUESTION_TYPE_CYCLE = ["summary", "authors", "date", "categories"]

# retrieval/qa.py picks which field to answer from by these phrases ("who authored", "when was",
# "what categories"; anything else answers from the summary), and a title in single quotes makes it
# look the paper up by exact title. The templates must keep that wording or the baseline scores
# low for reasons that have nothing to do with data quality.
QUESTION_TEMPLATES = {
    "summary": "What is the summary of the paper '{title}'?",
    "authors": "Who authored '{title}'?",
    "date": "When was '{title}' published?",
    "categories": "What categories does '{title}' belong to?",
}


def _ground_truth(question_type: str, row: pd.Series) -> str:
    """The answer in exactly the string form the index stores, so a correct answer scores token F1 = 1."""
    if question_type == "summary":
        return first_sentence(row["summary"])
    if question_type == "authors":
        return row["authors_joined"]
    if question_type == "date":
        return row["published"]
    return row["categories_joined"]


def _spread_positions(total: int, count: int) -> list[int]:
    """`count` row positions spread evenly from the oldest paper to the newest."""
    if count == 1:
        return [0]
    return sorted({round(step * (total - 1) / (count - 1)) for step in range(count)})


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build the fixed 10-question benchmark from the clean table and write it to test_set.json."""
    usable = df[~df["title"].str.contains("'", regex=False)].drop_duplicates(subset="paper_id")
    if len(usable) < TEST_SET_SIZE:
        raise ValueError(f"Need at least {TEST_SET_SIZE} usable papers for the test set, found {len(usable)}.")

    by_date = usable.sort_values(["published", "paper_id"]).reset_index(drop=True)
    samples: list[dict[str, Any]] = []
    for question_number, position in enumerate(_spread_positions(len(by_date), TEST_SET_SIZE), start=1):
        row = by_date.iloc[position]
        question_type = QUESTION_TYPE_CYCLE[(question_number - 1) % len(QUESTION_TYPE_CYCLE)]
        samples.append(
            {
                "id": f"eval_{question_number:03d}",
                "question_type": question_type,
                "question": QUESTION_TEMPLATES[question_type].format(title=row["title"]),
                "ground_truth": _ground_truth(question_type, row),
                "ground_truth_doc_ids": [row["paper_id"]],
            }
        )
    write_json(Path(output_path), samples)
    return samples


@dataclass(frozen=True)
class TestSet:
    samples: list[dict[str, Any]]


def load_or_create_test_set(df: pd.DataFrame, output_path, refresh: bool = False) -> TestSet:
    """Reuse the frozen test set when it still matches the corpus; otherwise build it.

    Also the entry point the lab handout (1.docx) calls in its Phase 3 check.
    """
    path = Path(output_path)
    if path.exists() and not refresh:
        samples = read_json(path)
        known_ids = set(df["paper_id"])
        if samples and all(doc_id in known_ids for sample in samples for doc_id in sample["ground_truth_doc_ids"]):
            return TestSet(samples=samples)
    return TestSet(samples=build_test_set(df, path))
