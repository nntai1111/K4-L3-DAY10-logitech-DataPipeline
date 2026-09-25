"""HTML building blocks. Every function returns a string; nothing here calls Streamlit.

``header``, ``metric_tiles``, ``banner``, ``empty_state``, ``user_bubble``, the markdown
converter and the source cards come from the K4A UI Kit (``K4A-UI-Kit/ui/components.py``),
with its retrieval-path wording turned into this project's four signals. The state cards,
gate table, freshness bars and scenario table are new and use the ``d10-*`` classes in
``day10.css``.

A whole source list goes out as one node, so the ``#src-<turn>-<n>`` citation anchors resolve.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .theme import COLORS, SIGNAL, SIGNAL_LABELS

STATE_ORDER = ("baseline", "corrupted", "repaired")
ORDERED_ITEM = re.compile(r"^\d+[\.\)]\s+")
BULLET_ITEM = re.compile(r"^[-*•]\s+")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def pill(label: str, tone: str = "neutral", *, dot: bool = False) -> str:
    inner = '<i class="d"></i>' if dot else ""
    return f'<span class="rag-pill" style="color:{SIGNAL[tone]}">{inner}{esc(label)}</span>'


def verdict(passed: bool, *, pass_text: str = "PASS", fail_text: str = "FAIL") -> str:
    tone = "pass" if passed else "problem"
    return f'<span class="d10-verdict" style="color:{SIGNAL[tone]}">{pass_text if passed else fail_text}</span>'


def section_label(text: str, *, note: str = "") -> str:
    tail = f'<span class="d10-label__note">{esc(note)}</span>' if note else ""
    return f'<div class="rag-label d10-label">{esc(text)}{tail}</div>'


# --- from the kit -----------------------------------------------------------------------
def header(title: str, subtitle: str, status: Sequence[tuple[str, str, str | None]]) -> str:
    """Product header and status strip. ``status`` is ``[(label, value, dot_colour)]``; the
    dot carries real state (gate passed or not), never decoration."""
    items = "".join(
        f'<div class="rag-strip__item"><div class="rag-strip__k">{esc(k)}</div>'
        '<div class="rag-strip__v">'
        + (f'<span class="dot" style="background:{dot}"></span>' if dot else "")
        + f"{esc(v)}</div></div>"
        for k, v, dot in status
    )
    return (
        '<div class="rag-header"><div class="rag-header__row">'
        '<div class="rag-mark">D10</div><div>'
        f'<p class="rag-title">{esc(title)}</p>'
        f'<p class="rag-sub">{esc(subtitle)}</p>'
        f'</div></div><div class="rag-strip">{items}</div></div>'
    )


def metric_tiles(tiles: Sequence[tuple[str, str, str, str]]) -> str:
    """``(label, value, sub, accent_colour)`` tiles."""
    body = "".join(
        f'<div class="rag-tile" style="--rag-accent:{accent}">'
        f'<div class="rag-tile__k">{esc(k)}</div>'
        f'<div class="rag-tile__v">{esc(v)}</div>'
        f'<div class="rag-tile__s">{esc(sub)}</div></div>'
        for k, v, sub, accent in tiles
    )
    return f'<div class="rag-tiles">{body}</div>'


def banner(message: str, *, kind: str = "info") -> str:
    """Inline notice. ``kind`` is ``info`` or ``warn``. ``message`` may hold markup."""
    glyph = "!" if kind == "warn" else "i"
    color = COLORS["muted"] if kind == "info" else SIGNAL["warning"]
    return (
        f'<div class="rag-banner rag-banner--{kind}">'
        f'<span class="rag-banner__ic" style="color:{color}">{glyph}</span>'
        f"<div>{message}</div></div>"
    )


def empty_state(title: str, subtitle: str) -> str:
    return (
        f'<div class="rag-empty"><div><div class="rag-empty__t">{esc(title)}</div>'
        f'<div class="rag-empty__s">{esc(subtitle)}</div></div></div>'
    )


def user_bubble(text: str) -> str:
    return f'<div class="rag-userq">{esc(text)}</div>'


def signal_legend() -> str:
    body = "".join(
        f'<div class="rag-legend__i"><i style="background:{SIGNAL[tone]}"></i>'
        f"<span>{esc(name)}</span><em>{esc(sub)}</em></div>"
        for tone, (name, sub) in SIGNAL_LABELS.items()
    )
    return f'<div class="rag-legend">{body}</div>'


def _inline_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)


def markdown_to_html(text: str) -> str:
    """The small markdown subset an LLM answer uses, on escaped text."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", esc(text).strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        # No backslashes inside f-string braces: the project still supports Python 3.11.
        if all(ORDERED_ITEM.match(line) for line in lines):
            out.append("<ol>" + "".join("<li>" + _inline_md(ORDERED_ITEM.sub("", line)) + "</li>" for line in lines) + "</ol>")
        elif all(BULLET_ITEM.match(line) for line in lines):
            out.append("<ul>" + "".join("<li>" + _inline_md(BULLET_ITEM.sub("", line)) + "</li>" for line in lines) + "</ul>")
        else:
            out.append("<p>" + _inline_md("<br>".join(lines)) + "</p>")
    return "".join(out)


# --- research assistant -----------------------------------------------------------------
def answer_card(answer: str, sources: Sequence[Mapping[str, Any]], turn: int) -> str:
    """The answer, with every DOI the agent cited turned into a numbered link to its card.
    A cited DOI the agent never retrieved stays visible in the problem colour, because
    silently dropping an unverifiable citation would hide the failure."""
    number_by_doi = {source["paper_id"].lower(): number for number, source in enumerate(sources, start=1)}

    def link(doi: str) -> str:
        number = number_by_doi.get(doi.strip().lower())
        if number is None:
            return f'<a class="rag-cite is-unmatched" title="Không khớp bài nào đã truy xuất">{esc(doi.strip())}</a>'
        return f'<a class="rag-cite" href="#src-{turn}-{number}" title="{esc(sources[number - 1]["title"])}">{number}</a>'

    def replace(match: re.Match[str]) -> str:
        return "".join(link(doi) for doi in match.group(1).split(","))

    body = re.sub(r"\[((?:\s*10\.\d{4,9}/[^\],\s]+\s*,?)+)\]", replace, markdown_to_html(answer))
    return f'<div class="rag-answer">{body}</div>'


def source_list(sources: Sequence[Mapping[str, Any]], *, turn: int) -> str:
    if not sources:
        return ""
    scores = [source["score"] for source in sources if source.get("score") is not None]
    low, high = (min(scores), max(scores)) if scores else (0.0, 1.0)
    cards = []
    for number, source in enumerate(sources, start=1):
        score = source.get("score")
        span = high - low
        ratio = 1.0 if score is None or span < 1e-9 else 0.16 + 0.84 * (score - low) / span
        score_html = (
            f'<div class="rag-src__score"><b>{score:.3f}</b><span>COSINE</span></div>' if score is not None
            else '<div class="rag-src__score"><b>exact</b><span>LOOKUP</span></div>'
        )
        cards.append(
            f'<div class="rag-src" id="src-{turn}-{number}" style="--rag-accent:{SIGNAL["evidence"]}">'
            '<div class="rag-src__head">'
            f'<div class="rag-src__n">{number}</div>'
            '<div class="flex-1 min-w-0">'
            f'<p class="rag-src__title">{esc(source["title"])}</p>'
            '<div class="rag-src__meta">'
            f'<span class="rag-src__file">{esc(source.get("authors_joined"))}</span>'
            f'<span class="rag-src__file">{esc(source.get("published"))}</span>'
            f'<a class="rag-src__link" href="{esc(source.get("abs_url"))}" target="_blank" rel="noopener">DOI</a>'
            "</div></div>"
            f"{score_html}</div>"
            f'<div class="rag-src__bar"><i style="width:{max(0.08, min(1.0, ratio)) * 100:.1f}%"></i></div>'
            "<details><summary>Tóm tắt</summary>"
            f'<div class="rag-chunk mt-2">{esc(source.get("summary") or "(trống)")}</div>'
            "</details></div>"
        )
    return f'<div class="rag-sources">{"".join(cards)}</div>'


def tool_calls(calls: Sequence[str]) -> str:
    if not calls:
        return ""
    return '<div class="d10-toolcalls">' + "".join(f'<span class="d10-toolcall">{esc(call)}</span>' for call in calls) + "</div>"


# --- observability ----------------------------------------------------------------------
def _delta(value: float, reference: float) -> str:
    delta = value - reference
    if abs(delta) < 5e-4:
        return ""
    tone = "problem" if delta < 0 else "pass"
    return f'<span class="d10-metric__d" style="color:{SIGNAL[tone]}">{delta:+.2f}</span>'


def state_cards(states: Mapping[str, Mapping[str, Any]]) -> str:
    """One card per state with the same four metrics in the same places, compared to baseline."""
    baseline = states["baseline"]["metrics"]
    cards = []
    for name in STATE_ORDER:
        state = states[name]
        metrics, quality = state["metrics"], state["quality"]
        rows = [
            ("Hit rate", metrics["retrieval_hit_rate"], baseline["retrieval_hit_rate"]),
            ("Token F1", metrics["mean_token_f1"], baseline["mean_token_f1"]),
            ("Judge accuracy", metrics["judge_accuracy"], baseline["judge_accuracy"]),
            ("Judge score", metrics["mean_judge_score"], baseline["mean_judge_score"]),
        ]
        metrics_html = "".join(
            f'<div><div class="d10-metric__k">{label}</div><div class="d10-metric__v">{value:.2f}'
            f"{_delta(value, reference) if name != 'baseline' else ''}</div></div>"
            for label, value, reference in rows
        )
        cards.append(
            '<div class="d10-state">'
            f'<div class="d10-state__head"><span class="d10-state__name">{esc(state["label"])}</span>'
            f"{verdict(quality['gate_passed'], pass_text='GATE PASS', fail_text='GATE FAIL')}</div>"
            f'<div class="d10-state__desc">{esc(state["description"])}</div>'
            f'<div class="d10-metrics">{metrics_html}</div></div>'
        )
    return f'<div class="d10-states">{"".join(cards)}</div>'


def _expectation_key(item: Mapping[str, Any]) -> str:
    return f"{item['expectation']}({item['column']})" if item.get("column") else item["expectation"]


EXPECTATION_TEXT = {
    "expect_table_row_count_to_be_between": "Số dòng trong khoảng 5 đến 5000",
    "expect_column_values_to_not_be_null(paper_id)": "paper_id không rỗng",
    "expect_column_values_to_not_be_null(title)": "title không rỗng",
    "expect_column_values_to_not_be_null(text_for_embedding)": "text_for_embedding không rỗng",
    "expect_column_values_to_be_unique(paper_id)": "paper_id không trùng",
    "expect_column_value_lengths_to_be_between(summary)": "summary dài ít nhất 30 ký tự",
    "expect_column_value_lengths_to_be_between(title)": "title dài ít nhất 10 ký tự",
    "expect_column_values_to_not_match_regex(summary)": "summary không chứa cụm ký tự rác",
}


def gate_table(states: Mapping[str, Mapping[str, Any]]) -> str:
    by_key = {name: {_expectation_key(item): item for item in states[name]["quality"]["expectations"]} for name in STATE_ORDER}
    rows = []
    for item in states["baseline"]["quality"]["expectations"]:
        key = _expectation_key(item)
        cells = []
        for name in STATE_ORDER:
            state_item = by_key[name][key]
            detail = f"<small>{state_item['unexpected_count']} dòng lỗi</small>" if not state_item["success"] and state_item.get("unexpected_count") else ""
            tone = "pass" if state_item["success"] else "problem"
            cells.append(f'<td><span class="d10-cell" style="color:{SIGNAL[tone]}">{"PASS" if state_item["success"] else "FAIL"}{detail}</span></td>')
        tier = "bắt buộc" if item["tier"] == "required" else "bổ sung"
        rows.append(f"<tr><td>{esc(EXPECTATION_TEXT.get(key, key))}<br><code>{esc(key)}</code></td><td>{tier}</td>{''.join(cells)}</tr>")
    freshness_cells = []
    for name in STATE_ORDER:
        freshness = states[name]["quality"]["freshness"]
        tone = "pass" if freshness["is_fresh"] else "warning"
        freshness_cells.append(
            f'<td><span class="d10-cell" style="color:{SIGNAL[tone]}">{"PASS" if freshness["is_fresh"] else "STALE"}'
            f"<small>{freshness['stale_rows']}/{freshness['total_rows']} dòng quá hạn</small></span></td>"
        )
    rows.append(f"<tr><td>Freshness SLA: tối đa 25% dòng quá 180 ngày<br><code>freshness_sla</code></td><td>SLA</td>{''.join(freshness_cells)}</tr>")
    head = "<tr><th>Kiểm tra</th><th>Loại</th>" + "".join(f"<th>{esc(states[name]['label'])}</th>" for name in STATE_ORDER) + "</tr>"
    return f'<div class="d10-table-wrap"><table class="d10-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def freshness_bars(states: Mapping[str, Mapping[str, Any]]) -> str:
    """Stale share per state on a 0 to 100% track, with the 25% SLA marked by a dashed line."""
    rows = []
    for name in STATE_ORDER:
        freshness = states[name]["quality"]["freshness"]
        ratio = freshness["stale_ratio"]
        tone = "pass" if freshness["is_fresh"] else "warning"
        rows.append(
            '<div class="d10-fresh__row">'
            f"<span>{esc(states[name]['label'])}</span>"
            f'<span class="d10-fresh__bar"><i style="width:{max(ratio, 0.01) * 100:.1f}%;background:{SIGNAL[tone]}"></i>'
            f'<b style="left:{freshness["max_stale_ratio"] * 100:.0f}%" title="SLA 25%"></b></span>'
            f'<span class="d10-fresh__v">{ratio:.0%} quá hạn</span></div>'
        )
    axis = '<div class="d10-fresh__axis">Nét đứt là ngưỡng SLA 25%. Bài mới nhất: ' + ", ".join(
        f"{esc(states[name]['label'])} {esc(states[name]['quality']['freshness']['latest_published'])}" for name in STATE_ORDER
    ) + ".</div>"
    return f'<div class="d10-fresh">{"".join(rows)}{axis}</div>'


def scenario_table(corruption_log: Mapping[str, Any], detectors: Mapping[str, str]) -> str:
    rows = "".join(
        f"<tr><td><code>{esc(scenario['scenario'])}</code></td><td class='num'>{scenario['rows_affected']}</td>"
        f"<td>{esc(scenario['description'])}</td><td>{detectors.get(scenario['scenario'], '')}</td></tr>"
        for scenario in corruption_log["scenarios"]
    )
    head = "<tr><th>Kịch bản</th><th>Dòng</th><th>Làm gì</th><th>Ai phát hiện</th></tr>"
    return f'<div class="d10-table-wrap"><table class="d10-table"><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


def question_table(answers_by_state: Mapping[str, Sequence[Mapping[str, Any]]], scenarios_by_paper: Mapping[str, list[str]]) -> str:
    by_id = {name: {answer["id"]: answer for answer in answers_by_state[name]} for name in STATE_ORDER}
    rows = []
    for answer in answers_by_state["baseline"]:
        touched = sorted({scenario for doc_id in answer["ground_truth_doc_ids"] for scenario in scenarios_by_paper.get(doc_id, [])})
        cells = []
        for name in STATE_ORDER:
            item = by_id[name][answer["id"]]
            tone = "pass" if item["retrieval_hit"] and item["token_f1"] >= 0.95 else "problem"
            cells.append(
                f'<td><span class="d10-cell" style="color:{SIGNAL[tone]}">F1 {item["token_f1"]:.2f}'
                f'<small>{"đúng bài" if item["retrieval_hit"] else "trượt bài"}</small></span></td>'
            )
        rows.append(
            f"<tr><td><code>{esc(answer['id'])}</code></td><td>{esc(answer['question_type'])}</td>"
            f"<td>{esc(', '.join(touched) or 'không')}</td>{''.join(cells)}</tr>"
        )
    head = "<tr><th>Câu</th><th>Loại</th><th>Bài bị tác động</th><th>Baseline</th><th>Corrupted</th><th>Repaired</th></tr>"
    return f'<div class="d10-table-wrap"><table class="d10-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
