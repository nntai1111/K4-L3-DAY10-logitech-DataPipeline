"""Design tokens and the stylesheet loader, from the K4A UI Kit used by the morning L3A demo.

``kit.css`` is the kit's compiled Tailwind build, copied byte for byte; rebuild it in the kit,
never edit it here. ``day10.css`` is plain CSS for what this page adds and only reads the
kit's --rag-* variables.

The kit's rule holds: colour is never decoration. Its four signal hues are renamed to the
four things a reader of this pipeline needs to tell apart:

    indigo  evidence  a paper the assistant retrieved or cited
    teal    pass      a check that passed, a question answered from the right paper
    amber   warning   stale data, or a score from the heuristic judge instead of the LLM
    rose    problem   a failed expectation, a retrieval miss, corrupted data

Baseline, corrupted and repaired are told apart by position and name, never by colour.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Final

import streamlit as st

COLORS: Final[dict[str, str]] = {
    "bg": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_2": "#F8FAFC",
    "border": "#E3E8F0",
    "text": "#101828",
    "text_dim": "#344054",
    "muted": "#667085",
    "faint": "#98A2B3",
    "accent": "#1E293B",
}

SIGNAL: Final[dict[str, str]] = {
    "evidence": "#4F46E5",
    "pass": "#0F766E",
    "warning": "#B45309",
    "problem": "#BE123C",
    "neutral": "#1E293B",
}

SIGNAL_LABELS: Final[dict[str, tuple[str, str]]] = {
    "evidence": ("Bằng chứng", "bài báo được truy xuất hoặc trích dẫn"),
    "pass": ("Đạt", "kiểm tra qua, trả lời đúng bài"),
    "warning": ("Cảnh báo", "dữ liệu cũ, hoặc điểm do heuristic chấm"),
    "problem": ("Lỗi", "expectation fail, truy xuất trượt, dữ liệu bẩn"),
}

HERE: Final[Path] = Path(__file__).resolve().parent
STYLESHEETS: Final[tuple[Path, ...]] = (HERE / "kit.css", HERE / "day10.css")
FONT_LINKS: Final[str] = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    "?family=Be+Vietnam+Pro:wght@300;400;500;600;700"
    "&family=Noto+Serif:opsz,wght@8..144,500;8..144,600;8..144,700"
    '&family=JetBrains+Mono:wght@400;500;600&display=swap">'
)


@lru_cache(maxsize=1)
def stylesheet() -> str:
    """Both stylesheets on one line. st.markdown ends a raw HTML block at the first blank line,
    so a multi-line stylesheet would print every rule after that line as page text."""
    css = "\n".join(path.read_text(encoding="utf-8") for path in STYLESHEETS)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.sub(r"\s+", " ", css).strip()


def inject_css() -> None:
    # Never st.html: its sanitiser deletes <style> and <link> without logging anything, and a
    # hot reload hides that because the previous render's styles stay in the DOM.
    st.markdown(f"{FONT_LINKS}<style>{stylesheet()}</style>", unsafe_allow_html=True)
