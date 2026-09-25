from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class EvaluationSample:
    id: str
    type: str
    question: str
    ground_truth: str
    ground_truth_doc_ids: list[str]


@dataclass
class EvaluationTestSet:
    samples: list[EvaluationSample]


def build_test_set(df: pd.DataFrame, output_path: Path | str) -> list[dict[str, Any]]:
    """Tao bo evaluation test set gom 5 dang cau hoi tu cleaned dataframe."""
    if df.empty:
        raise ValueError("Clean dataframe is empty, cannot build test set.")

    samples: list[dict[str, Any]] = []
    records = df.to_dict(orient="records")
    num_records = len(records)

    # 1. Summary questions
    for i in range(min(2, num_records)):
        r = records[i]
        samples.append(
            {
                "id": f"eval_{len(samples)+1:03d}",
                "type": "summary",
                "question_type": "summary",
                "question": f"What is the summary of the paper '{r['title']}'?",
                "ground_truth": r["summary"],
                "ground_truth_doc_ids": [r["paper_id"]],
            }
        )

    # 2. Authors questions
    for i in range(min(2, num_records)):
        idx = (i + 1) % num_records
        r = records[idx]
        authors_str = r.get("authors_joined") or ", ".join(r.get("authors", []))
        samples.append(
            {
                "id": f"eval_{len(samples)+1:03d}",
                "type": "authors",
                "question_type": "authors",
                "question": f"Who are the authors of the paper '{r['title']}'?",
                "ground_truth": authors_str,
                "ground_truth_doc_ids": [r["paper_id"]],
            }
        )

    # 3. Date questions
    for i in range(min(2, num_records)):
        idx = (i + 2) % num_records
        r = records[idx]
        samples.append(
            {
                "id": f"eval_{len(samples)+1:03d}",
                "type": "date",
                "question_type": "date",
                "question": f"When was the paper '{r['title']}' published?",
                "ground_truth": str(r["published"]),
                "ground_truth_doc_ids": [r["paper_id"]],
            }
        )

    # 4. Category questions
    for i in range(min(2, num_records)):
        idx = (i + 3) % num_records
        r = records[idx]
        cats = r.get("categories_joined") or ", ".join(r.get("categories", []))
        samples.append(
            {
                "id": f"eval_{len(samples)+1:03d}",
                "type": "category",
                "question_type": "category",
                "question": f"What domain or categories does the paper '{r['title']}' belong to?",
                "ground_truth": cats,
                "ground_truth_doc_ids": [r["paper_id"]],
            }
        )

    # 5. Multi-hop questions
    if num_records >= 2:
        r1, r2 = records[0], records[1]
        cats1 = r1.get("categories_joined", "AI")
        cats2 = r2.get("categories_joined", "Data Systems")
        samples.append(
            {
                "id": f"eval_{len(samples)+1:03d}",
                "type": "multi_hop",
                "question_type": "multi_hop",
                "question": f"Compare the research topics of '{r1['title']}' and '{r2['title']}'. What are their main fields?",
                "ground_truth": f"Paper 1 covers {cats1} while Paper 2 covers {cats2}.",
                "ground_truth_doc_ids": [r1["paper_id"], r2["paper_id"]],
            }
        )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")

    return samples


def load_or_create_test_set(df: pd.DataFrame, output_path: Path | str) -> EvaluationTestSet:
    """Load existing test set file or build a new one."""
    out_path = Path(output_path)
    if out_path.exists():
        raw_samples = json.loads(out_path.read_text(encoding="utf-8"))
    else:
        raw_samples = build_test_set(df, out_path)

    sample_objs = [
        EvaluationSample(
            id=s["id"],
            type=s.get("type", s.get("question_type", "summary")),
            question=s["question"],
            ground_truth=s["ground_truth"],
            ground_truth_doc_ids=list(s["ground_truth_doc_ids"]),
        )
        for s in raw_samples
    ]
    return EvaluationTestSet(samples=sample_objs)

