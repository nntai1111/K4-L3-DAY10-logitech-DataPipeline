"""One demo question per corruption scenario, for the Silent failure tab.

The fixed 10-question test set is what the metrics are computed on, and it only happens to hit
some scenarios in a visible way. For a demo, each scenario gets its own question: among the
papers that scenario touched, and the four question types, pick the one where the corrupted
collection's answer goes most visibly wrong. These questions never feed any metric.
"""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from core.config import Settings
from core.utils import read_json
from evaluation.metrics import _token_f1 as token_f1
from evaluation.testset import QUESTION_TEMPLATES, _ground_truth
from retrieval.index import LocalEmbeddingIndex
from retrieval.qa import answer_question

# Demo order: the stale-knowledge story from the lab brief first, then the most visible ones.
SCENARIO_TEXT = {
    "stale_date": ("Ngày bị làm cũ", "Ngày xuất bản bị lùi 365 ngày. Trợ lý trả lời sai năm mà không hề nghi ngờ."),
    "drop_latest_records": ("Mất bài mới nhất", "4 bài mới nhất biến mất khỏi kho. Không expectation nào bắt được, trợ lý đọc nhầm sang bài khác."),
    "inject_text_noise": ("Chèn ký tự rác", "Summary bị chèn ký tự rác. Câu trả lời mang nguyên rác ra cho người dùng."),
    "blank_summary": ("Xóa tóm tắt", "Summary bị xóa trắng. Trợ lý trả lời rỗng thay vì báo thiếu dữ liệu."),
    "truncate_title": ("Cắt tiêu đề", "Tiêu đề bị cắt còn 7 ký tự, tra theo tên thất bại, trợ lý lấy nhầm bài khác."),
    "duplicate_rows": ("Nhân bản dòng", "Một bài bị nhân đôi và chiếm nhiều chỗ trong top-4 nguồn, đẩy bài khác ra ngoài."),
}


@dataclass(frozen=True)
class DemoCase:
    scenario: str
    label: str
    story: str
    paper_id: str
    question_type: str
    question: str
    ground_truth: str


def _visibility(scenario: str, paper_id: str, ground_truth: str, answer) -> float:
    retrieved = answer.retrieved_doc_ids
    duplicates = len(retrieved) - len(set(retrieved))
    if scenario == "duplicate_rows":
        return float(duplicates)
    wrong = 1.0 - token_f1(ground_truth, answer.answer)
    missed = 0.0 if paper_id in retrieved else 1.0
    return wrong + missed + 0.25 * bool(duplicates)


def build_demo_cases(settings: Settings, corrupted_index: LocalEmbeddingIndex) -> list[DemoCase]:
    clean = pd.DataFrame(read_json(settings.paths.clean_json)).set_index("paper_id")
    scenarios = {item["scenario"]: item for item in read_json(settings.paths.corruption_log)["scenarios"]}
    cases: list[DemoCase] = []
    for scenario, (label, story) in SCENARIO_TEXT.items():
        if scenario not in scenarios:
            continue
        best: tuple[float, str, str, str, str] | None = None
        for paper_id in scenarios[scenario]["paper_ids"]:
            row = clean.loc[paper_id]
            for question_type, template in QUESTION_TEMPLATES.items():
                question = template.format(title=row["title"])
                ground_truth = _ground_truth(question_type, row)
                answer = answer_question(question, settings=settings, index=corrupted_index)
                score = _visibility(scenario, paper_id, ground_truth, answer)
                if best is None or score > best[0]:
                    best = (score, paper_id, question_type, question, ground_truth)
        if best:
            _, paper_id, question_type, question, ground_truth = best
            cases.append(DemoCase(scenario, label, story, paper_id, question_type, question, ground_truth))
    return cases


def duplicate_count(retrieved_doc_ids: list[str]) -> int:
    return len(retrieved_doc_ids) - len(set(retrieved_doc_ids))


def corpus_topics(settings: Settings, limit: int = 6) -> list[str]:
    """The most common categories in the clean corpus, for the out-of-scope card."""
    counts: dict[str, int] = {}
    for row in read_json(settings.paths.clean_json):
        for category in row["categories"]:
            counts[category] = counts.get(category, 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]
