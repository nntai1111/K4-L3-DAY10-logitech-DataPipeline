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


# --- diff highlighting ------------------------------------------------------------------
# Sentinels survive escaping and markdown conversion, then become <mark>. Control characters
# never occur in model output or in the corpus.
MARK_OPEN, MARK_CLOSE = "\x01", "\x02"
DOI_PATTERN = re.compile(r"\[((?:\s*10\.\d{4,9}/[^\],\s]+\s*,?)+)\]")


def _norm(token: str) -> str:
    return token.strip(".,;:!?()[]\"'*").lower()


def mark_new_words(text: str, reference: str) -> str:
    """Wrap every word of ``text`` that ``reference`` does not contain in sentinels.
    DOIs are left alone so citations still link."""
    known = {_norm(word) for word in reference.split()}
    marked = []
    for word in text.split(" "):
        stripped = _norm(word)
        if stripped and stripped not in known and "10." not in word:
            marked.append(f"{MARK_OPEN}{word}{MARK_CLOSE}")
        else:
            marked.append(word)
    return " ".join(marked)


def _apply_marks(markup: str) -> str:
    return markup.replace(MARK_OPEN, '<mark class="d10-diff">').replace(MARK_CLOSE, "</mark>")


def cited_dois(answer: str) -> set[str]:
    return {doi.strip().lower() for match in DOI_PATTERN.finditer(answer) for doi in match.group(1).split(",")}


# --- research assistant -----------------------------------------------------------------
def answer_card(answer: str, sources: Sequence[Mapping[str, Any]], turn: int, *, compare_to: str | None = None) -> str:
    """The answer, with every DOI the agent cited turned into a numbered link to its card.
    A cited DOI the agent never retrieved stays visible in the problem colour, because
    silently dropping an unverifiable citation would hide the failure. With ``compare_to``,
    words that the reference answer does not contain are highlighted."""
    if compare_to is not None:
        answer = mark_new_words(answer, compare_to)
    number_by_doi = {source["paper_id"].lower(): number for number, source in enumerate(sources, start=1)}

    def link(doi: str) -> str:
        number = number_by_doi.get(doi.strip().lower())
        if number is None:
            return f'<a class="rag-cite is-unmatched" title="Không khớp bài nào đã truy xuất">{esc(doi.strip())}</a>'
        return f'<a class="rag-cite" href="#src-{turn}-{number}" title="{esc(sources[number - 1]["title"])}">{number}</a>'

    def replace(match: re.Match[str]) -> str:
        return "".join(link(doi) for doi in match.group(1).split(","))

    body = _apply_marks(DOI_PATTERN.sub(replace, markdown_to_html(answer)))
    return f'<div class="rag-answer">{body}</div>'


def out_of_scope_card(answer: str, searches: Sequence[str], best_score: float | None, topics: Sequence[str], *, papers: int = 24) -> str:
    """The agent searched, found nothing relevant and said so: a deliberate outcome, styled
    like the Day 08 kit's refusal card rather than as an error."""
    searched = ", ".join(searches) or "không gọi công cụ"
    score = f"cosine cao nhất {best_score:.3f}" if best_score is not None else "không có kết quả"
    return (
        '<div class="rag-refusal">'
        '<div class="rag-refusal__h"><span class="ic">!</span>Ngoài phạm vi kho bài báo</div>'
        f'<div class="rag-refusal__b">{markdown_to_html(answer)}</div>'
        f'<div class="rag-refusal__n">Agent đã tìm ({esc(searched)}) nhưng không bài nào đủ liên quan, {score}. '
        f"Kho có {papers} bài" + (f" về: {esc(', '.join(topics))}" if topics else "") + ".</div>"
        "</div>"
    )


def source_list(sources: Sequence[Mapping[str, Any]], *, turn: int, cited: set[str] | None = None) -> str:
    """Source cards. With ``cited``, papers the answer did not cite are dimmed and labelled,
    so a paper that was only read is never mistaken for evidence."""
    if not sources:
        return ""
    scores = [source["score"] for source in sources if source.get("score") is not None]
    low, high = (min(scores), max(scores)) if scores else (0.0, 1.0)
    cards = []
    for number, source in enumerate(sources, start=1):
        score = source.get("score")
        span = high - low
        ratio = 1.0 if score is None or span < 1e-9 else 0.16 + 0.84 * (score - low) / span
        if score is not None:
            score_html = f'<div class="rag-src__score"><b>{score:.3f}</b><span>COSINE</span></div>'
        elif source.get("via") == "filter":
            score_html = '<div class="rag-src__score"><b>lọc</b><span>METADATA</span></div>'
        else:
            score_html = '<div class="rag-src__score"><b>exact</b><span>LOOKUP</span></div>'

        used = cited is None or source["paper_id"].lower() in cited
        unused_tag = "" if used else '<span class="d10-unused">đã đọc, không trích dẫn</span>'
        cards.append(
            f'<div class="rag-src{"" if used else " d10-src--unused"}" id="src-{turn}-{number}" style="--rag-accent:{SIGNAL["evidence"]}">'
            '<div class="rag-src__head">'
            f'<div class="rag-src__n">{number}</div>'
            '<div class="flex-1 min-w-0">'
            f'<p class="rag-src__title">{esc(source["title"])}</p>'
            f'<div class="rag-src__meta">{unused_tag}'
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


# --- silent failure ---------------------------------------------------------------------
def comparison_cards(rows: Sequence[Mapping[str, Any]], *, ground_truth: str | None = None) -> str:
    """The same question answered on each collection. Each row holds label, answer, the top
    source's metadata, hit and f1 (None for a free question), duplicates in the top-k and the
    scenarios that touched the paper. A card that went wrong gets the problem stripe, a verdict
    line, and the words that are not in the ground truth highlighted."""
    cards = []
    for row in rows:
        verdicts = []
        if row.get("hit") is not None:
            verdicts.append(pill("đúng bài" if row["hit"] else "đọc nhầm bài", "pass" if row["hit"] else "problem"))
        if row.get("f1") is not None:
            verdicts.append(pill(f"F1 {row['f1']:.2f}", "pass" if row["f1"] >= 0.95 else "problem"))
        duplicates = row.get("duplicates", 0)
        answer = row["answer"].strip()
        problems = []
        if row.get("hit") is False:
            problems.append("Câu trả lời lấy từ một bài khác bài được hỏi.")
        if not answer:
            problems.append("Trả lời rỗng, không báo thiếu dữ liệu.")
        elif row.get("f1") is not None and row["f1"] < 0.95:
            problems.append("Sai so với đáp án chuẩn, không có cảnh báo nào.")
        notes = []
        if duplicates:
            duplicate_text = f"Top-4 nguồn có {duplicates} bản trùng của cùng một bài."
            # A duplicate is the headline only when nothing worse happened; otherwise it is a side note.
            (notes if problems else problems).append(duplicate_text)

        if not answer:
            answer_html = f'<span style="color:{SIGNAL["problem"]}">(trả lời rỗng)</span>'
        elif ground_truth is not None:
            answer_html = _apply_marks(esc(mark_new_words(answer, ground_truth)))
        else:
            answer_html = esc(answer)
        source = row.get("source")
        if source:
            source_html = (
                f'<div class="d10-cmp__src">Đọc từ: <b>{esc(source["title"])}</b><br>'
                f'{esc(source["published"])}, {esc(source["authors_joined"])}</div>'
            )
        else:
            source_html = '<div class="d10-cmp__src">Không truy xuất được bài nào.</div>'
        touched = row.get("touched") or []
        touched_html = (
            f'<div class="d10-cmp__touch">Bài đúng bị tác động bởi <code>{esc(", ".join(touched))}</code></div>' if touched else ""
        )
        problem_html = "".join(f'<div class="d10-cmp__problem">{esc(text)}</div>' for text in problems)
        problem_html += "".join(f'<div class="d10-cmp__note">{esc(text)}</div>' for text in notes)
        cards.append(
            f'<div class="d10-state{" d10-state--bad" if problems else ""}">'
            f'<div class="d10-state__head"><span class="d10-state__name">{esc(row["label"])}</span>'
            f'<span class="d10-cmp__verdicts">{"".join(verdicts)}</span></div>'
            f'<div class="d10-cmp__answer">{answer_html}</div>{problem_html}{source_html}{touched_html}</div>'
        )
    return f'<div class="d10-states">{"".join(cards)}</div>'


def ground_truth_line(question_type: str, ground_truth: str) -> str:
    return (
        '<div class="d10-truth"><span class="rag-label">Đáp án chuẩn</span>'
        f'<span class="d10-truth__type">{esc(question_type)}</span><span class="d10-truth__v">{esc(ground_truth)}</span></div>'
    )


# --- agent steps and live ingest --------------------------------------------------------
TOOL_TEXT = {
    "semantic_search_papers": "tìm theo nghĩa",
    "lookup_paper": "tra đúng bài",
    "find_papers_by_author": "lọc theo tác giả",
    "find_papers_by_date": "lọc theo ngày",
    "ingest_new_papers": "nạp bài mới qua gate",
}


def agent_steps(steps: Sequence[Mapping[str, str]]) -> str:
    """The ReAct path: each tool the agent chose, what it asked, and what came back."""
    if not steps:
        return ""
    items = []
    for number, step in enumerate(steps, start=1):
        thought = f'<div class="d10-step__thought">{esc(step["thought"][:220])}</div>' if step.get("thought") else ""
        observation = f'<span class="d10-step__obs">{esc(step.get("observation") or "")}</span>' if step.get("observation") else ""
        items.append(
            f'<li class="d10-step">{thought}<div class="d10-step__line">'
            f'<span class="d10-step__n">{number}</span>'
            f'<span class="d10-step__tool" title="{esc(step["tool"])}">{esc(TOOL_TEXT.get(step["tool"], step["tool"]))}</span>'
            f'<code class="d10-step__arg">{esc(step.get("argument") or "")}</code>{observation}</div></li>'
        )
    return f'<ol class="d10-steps">{"".join(items)}</ol>'


def _stage(value: str, caption: str, state: str) -> str:
    """One pipeline stage. ``state`` is ok, bad, warn, plain or skip (never reached)."""
    return f'<li class="d10-pipe__s is-{state}"><b>{esc(value)}</b><span>{esc(caption)}</span></li>'


def ingest_card(result: Any) -> str:
    """One live ingest, stage by stage, from Crossref to the collection the agent answers from."""
    blocked = not result.indexed
    batch_gate = result.batch_gate_passed
    merged_gate = result.merged_gate_passed
    stages = [
        _stage(str(result.fetched), "từ Crossref", "plain" if result.fetched else "bad"),
        _stage(str(result.batch_rows), "sau làm sạch", "plain" if result.batch_rows else "skip"),
        _stage(str(len(result.quarantined)), "bị cách ly", "warn" if result.quarantined else "plain"),
        _stage("PASS" if batch_gate else "FAIL" if batch_gate is False else "—", "gate lô mới",
               "ok" if batch_gate else "bad" if batch_gate is False else "skip"),
        _stage(f"+{result.new_papers}" if merged_gate is not None else "—", "bài mới",
               "plain" if merged_gate is not None else "skip"),
        _stage("PASS" if merged_gate else "FAIL" if merged_gate is False else "—", "gate kho gộp",
               "ok" if merged_gate else "bad" if merged_gate is False else "skip"),
        _stage(str(result.total_papers) if merged_gate is not None else "—", "bài trong kho",
               "plain" if merged_gate is not None else "skip"),
    ]
    if blocked:
        verdict_html = f'<span class="d10-verdict" style="color:{SIGNAL["problem"]}">BỊ CHẶN</span>'
        note = f'<div class="d10-ingest__reason">Không nạp gì, kho giữ nguyên. Lý do: {esc(result.blocked_reason)}</div>'
    elif result.new_papers:
        verdict_html = f'<span class="d10-verdict" style="color:{SIGNAL["pass"]}">ĐÃ NẠP +{result.new_papers}</span>'
        note = ""
    else:
        verdict_html = f'<span class="d10-verdict" style="color:{SIGNAL["neutral"]}">KHÔNG CÓ BÀI MỚI</span>'
        note = f'<div class="d10-ingest__reason is-plain">Lô mới qua gate, nhưng cả {result.already_indexed} bài đã có trong kho.</div>'
    quarantine = ""
    if result.quarantined:
        rows = "".join(
            f'<li><code>{esc(row["paper_id"])}</code> {esc(row["reason"])}<br><span>{esc(row["title"][:110])}</span></li>'
            for row in result.quarantined
        )
        quarantine = f'<details class="d10-ingest__more"><summary>{len(result.quarantined)} bài bị cách ly</summary><ul>{rows}</ul></details>'
    added = ""
    if result.added:
        rows = "".join(
            f'<li><span class="d10-ingest__date">{esc(paper["published"])}</span>{esc(paper["title"][:120])}</li>'
            for paper in result.added
        )
        added = f'<details class="d10-ingest__more"><summary>{len(result.added)} bài mới đã index</summary><ul>{rows}</ul></details>'
    return (
        f'<div class="d10-ingest{" d10-ingest--blocked" if blocked else ""}">'
        '<div class="d10-ingest__head"><div>'
        '<div class="rag-label">Nạp dữ liệu live</div>'
        f'<div class="d10-ingest__topic">{esc(result.topic)}<span>xuất bản từ {esc(result.published_since)}</span></div>'
        f"</div>{verdict_html}</div>"
        f'<ol class="d10-pipe">{"".join(stages)}</ol>{note}{quarantine}{added}'
        f'<div class="d10-ingest__foot">{result.seconds:.1f} s · Great Expectations + freshness SLA · báo cáo trong data/live/quality</div>'
        "</div>"
    )


def ingest_history_table(history: Sequence[Mapping[str, Any]]) -> str:
    """Every live ingest the agent ran, newest first, from data/live/ingest_log."""
    rows = []
    for item in history:
        at = str(item.get("at", ""))
        when = f"{at[9:11]}:{at[11:13]}:{at[13:15]}" if len(at) >= 15 else at
        gate = verdict(bool(item.get("indexed")), pass_text="NẠP", fail_text="CHẶN")
        rows.append(
            f"<tr><td class=\"num\">{esc(when)}</td><td>{esc(item.get('topic'))}</td>"
            f"<td class=\"num\">{item.get('fetched', 0)}</td><td class=\"num\">{len(item.get('quarantined') or [])}</td>"
            f"<td>{gate}</td><td class=\"num\">+{item.get('new_papers', 0) if item.get('indexed') else 0}</td>"
            f"<td class=\"num\">{item.get('total_papers', 0)}</td>"
            f"<td>{esc(item.get('blocked_reason') or '')}</td></tr>"
        )
    return (
        '<div class="d10-table-wrap"><table class="d10-table"><thead><tr>'
        "<th>Giờ (UTC)</th><th>Chủ đề</th><th>Crossref</th><th>Cách ly</th><th>Gate</th><th>Thêm</th><th>Kho</th><th>Lý do chặn</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def gate_stat_tiles(stats: Mapping[str, Any]) -> str:
    """Headline numbers for the live gate: runs, verdicts, rows in, rows held back, rows added."""
    rate = f"{stats['pass_rate']:.0%} qua gate" if stats["pass_rate"] is not None else "chưa chạy"
    held = f"{stats['quarantined'] / stats['fetched']:.0%} số bài lấy về" if stats["fetched"] else "—"
    return metric_tiles([
        ("Lần nạp", str(stats["runs"]), rate, SIGNAL["neutral"]),
        ("Qua gate", str(stats["passed"]), "được index", SIGNAL["pass"]),
        ("Bị chặn", str(stats["blocked"]), "kho giữ nguyên", SIGNAL["problem"]),
        ("Bài lấy về", str(stats["fetched"]), "từ Crossref", SIGNAL["evidence"]),
        ("Bị cách ly", str(stats["quarantined"]), held, SIGNAL["warning"]),
        ("Bài thêm vào kho", f"+{stats['added']}", "sau hai lần gate", SIGNAL["pass"]),
    ])


def reason_bars(title: str, counts: Mapping[str, int], *, tone: str, empty: str) -> str:
    """How often each reason occurred, as bars on a shared scale."""
    if not counts:
        body = f'<div class="d10-fresh__axis">{esc(empty)}</div>'
    else:
        top = max(counts.values())
        body = "".join(
            '<div class="d10-reason__row">'
            f"<span>{esc(label)}</span>"
            f'<span class="d10-fresh__bar"><i style="width:{max(count / top, 0.04) * 100:.1f}%;background:{SIGNAL[tone]}"></i></span>'
            f'<span class="d10-fresh__v">{count}</span></div>'
            for label, count in counts.items()
        )
    return f'<div class="d10-fresh"><div class="rag-label" style="margin:0">{esc(title)}</div>{body}</div>'


def gate_stat_line(stats: Mapping[str, Any]) -> str:
    """One line for the sidebar."""
    if not stats["runs"]:
        return '<div class="d10-mode">Gate live: chưa có lần nạp nào.</div>'
    return (
        f'<div class="d10-mode">Gate live: {stats["runs"]} lần nạp, '
        f'<span style="color:{SIGNAL["pass"]}">{stats["passed"]} qua</span>, '
        f'<span style="color:{SIGNAL["problem"]}">{stats["blocked"]} chặn</span>, '
        f'{stats["quarantined"]} bài cách ly, +{stats["added"]} bài vào kho.</div>'
    )
