"""Reads the pipeline's artifacts from data/. The only module in app/ that touches files.

The page shows what the last runs of `script/run_phase1.py` and `script/run_corruption_flow.py`
wrote. It never runs the pipeline itself, so opening it costs no API quota.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import Settings
from core.utils import read_json

STATE_TEXT = {
    "baseline": ("Baseline", "Dữ liệu sạch từ snapshot Crossref"),
    "corrupted": ("Corrupted", "Sau 6 kịch bản tiêm lỗi"),
    "repaired": ("Repaired", "Dựng lại từ raw, cùng run_date"),
}


@dataclass(frozen=True)
class Artifacts:
    states: dict[str, dict[str, Any]]
    run_context: dict[str, Any] | None
    corruption_log: dict[str, Any] | None
    repair: dict[str, Any] | None
    missing: list[str]

    @property
    def phase1_ready(self) -> bool:
        return "baseline" in self.states

    @property
    def comparison_ready(self) -> bool:
        return all(name in self.states for name in STATE_TEXT)

    def scenarios_by_paper(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = defaultdict(list)
        for scenario in (self.corruption_log or {}).get("scenarios", []):
            for paper_id in scenario["paper_ids"]:
                mapping[paper_id].append(scenario["scenario"])
        return mapping


def _state_files(settings: Settings) -> dict[str, dict[str, Path]]:
    paths = settings.paths
    return {
        "baseline": {"metrics": paths.baseline_metrics, "answers": paths.baseline_answers, "quality": paths.baseline_quality_report},
        "corrupted": {"metrics": paths.corrupted_metrics, "answers": paths.corrupted_answers, "quality": paths.corrupted_quality_report},
        "repaired": {
            "metrics": paths.repaired_metrics,
            "answers": paths.repaired_answers,
            "quality": paths.quality_dir / "repaired_quality_report.json",
        },
    }


def _optional(path: Path) -> Any | None:
    return read_json(path) if path.exists() else None


def load_artifacts(settings: Settings) -> Artifacts:
    states: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, files in _state_files(settings).items():
        absent = [path for path in files.values() if not path.exists()]
        if absent:
            missing += [path.relative_to(settings.paths.project_dir).as_posix() for path in absent]
            continue
        label, description = STATE_TEXT[name]
        states[name] = {"label": label, "description": description, **{key: read_json(path) for key, path in files.items()}}
    return Artifacts(
        states=states,
        run_context=_optional(settings.paths.run_context),
        corruption_log=_optional(settings.paths.corruption_log),
        repair=_optional(settings.paths.project_dir / "data" / "results" / "repair_idempotency.json"),
        missing=missing,
    )
