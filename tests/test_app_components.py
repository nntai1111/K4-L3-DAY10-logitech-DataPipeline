"""app/ui/components.py: the pure HTML string builders behind the agent trace and the live gate.

Nothing here renders Streamlit; each builder is called with hand-built inputs and its markup is
checked for the numbers, words, CSS state classes and escaping the page relies on.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

from pipelines.live_ingest import IngestResult, gate_stats

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:  # app/ is not a package; streamlit runs it as a script folder
    sys.path.append(str(APP_DIR))

from ui import components as ui  # noqa: E402
from ui.theme import SIGNAL  # noqa: E402

INJECTION = '<script>alert("x")</script>'
ESCAPED = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
STAGE = re.compile(r'<li class="d10-pipe__s is-(\w+)"><b>(.*?)</b><span>(.*?)</span></li>')


def stages(markup: str) -> dict[str, tuple[str, str]]:
    """Pipeline stages of an ingest card: caption -> (state, value)."""
    return {caption: (state, value) for state, value, caption in STAGE.findall(markup)}


# --- agent_steps -------------------------------------------------------------------------------


def test_agent_steps_without_steps_is_empty():
    assert ui.agent_steps([]) == ""


def test_agent_steps_numbers_each_tool_call_in_words():
    markup = ui.agent_steps([
        {"tool": "find_papers_by_author", "argument": INJECTION, "observation": "2 bài", "thought": "Tìm theo tác giả trước."},
        {"tool": "find_papers_by_date", "argument": "sau 2026-06, trước 2026-08", "observation": "", "thought": ""},
        {"tool": "some_new_tool", "argument": "x", "observation": "No paper <b>here</b>", "thought": ""},
    ])

    assert markup.startswith('<ol class="d10-steps">') and markup.endswith("</ol>")
    assert markup.count('<li class="d10-step">') == 3
    assert re.findall(r'<span class="d10-step__n">(\d+)</span>', markup) == ["1", "2", "3"]
    labels = re.findall(r'<span class="d10-step__tool" title="([^"]+)">([^<]+)</span>', markup)
    assert labels == [
        ("find_papers_by_author", ui.TOOL_TEXT["find_papers_by_author"]),
        ("find_papers_by_date", ui.TOOL_TEXT["find_papers_by_date"]),
        ("some_new_tool", "some_new_tool"),
    ], "an unknown tool falls back to its own name"
    assert ui.TOOL_TEXT["find_papers_by_author"] == "lọc theo tác giả"
    assert INJECTION not in markup and ESCAPED in markup
    assert "No paper &lt;b&gt;here&lt;/b&gt;" in markup
    assert markup.count('class="d10-step__thought"') == 1 and "Tìm theo tác giả trước." in markup
    assert markup.count('class="d10-step__obs"') == 2, "an empty observation leaves no span"


def test_agent_steps_escapes_and_trims_the_thought():
    markup = ui.agent_steps([{"tool": "lookup_paper", "argument": "", "thought": "<i>" + "y" * 300}])
    [thought] = re.findall(r'<div class="d10-step__thought">(.*?)</div>', markup)
    assert thought == "&lt;i&gt;" + "y" * 217, "the first 220 characters, escaped"
    assert '<code class="d10-step__arg"></code>' in markup


# --- ingest_card -------------------------------------------------------------------------------


ADDED = [
    {"paper_id": f"10.9999/vla.{number}", "title": f"Vision-language-action study {number}", "published": f"2026-09-1{number}"}
    for number in range(1, 4)
]


def test_ingest_card_for_new_papers():
    result = IngestResult(
        topic="vla robots",
        published_since="2026-03-29",
        fetched=7,
        batch_rows=6,
        batch_gate_passed=True,
        new_papers=3,
        already_indexed=3,
        merged_gate_passed=True,
        total_papers=27,
        indexed=True,
        added=ADDED,
        seconds=3.3,
    )
    markup = ui.ingest_card(result)

    assert "d10-ingest--blocked" not in markup
    assert f'<span class="d10-verdict" style="color:{SIGNAL["pass"]}">ĐÃ NẠP +3</span>' in markup
    assert stages(markup) == {
        "từ Crossref": ("plain", "7"),
        "sau làm sạch": ("plain", "6"),
        "bị cách ly": ("plain", "0"),
        "gate lô mới": ("ok", "PASS"),
        "bài mới": ("plain", "+3"),
        "gate kho gộp": ("ok", "PASS"),
        "bài trong kho": ("plain", "27"),
    }
    assert "vla robots<span>xuất bản từ 2026-03-29</span>" in markup
    assert "<summary>3 bài mới đã index</summary>" in markup
    for paper in ADDED:
        assert f'<span class="d10-ingest__date">{paper["published"]}</span>{paper["title"]}' in markup
    assert "bị cách ly</summary>" not in markup and "d10-ingest__reason" not in markup
    assert "3.3 s · Great Expectations" in markup


def test_ingest_card_when_nothing_is_new():
    result = IngestResult(
        topic="vla robots",
        published_since="2026-03-29",
        fetched=5,
        batch_rows=5,
        batch_gate_passed=True,
        already_indexed=5,
        merged_gate_passed=True,
        total_papers=29,
        indexed=True,
    )
    markup = ui.ingest_card(result)

    assert "KHÔNG CÓ BÀI MỚI" in markup and "ĐÃ NẠP" not in markup and "BỊ CHẶN" not in markup
    assert "cả 5 bài đã có trong kho" in markup
    assert stages(markup)["bài mới"] == ("plain", "+0") and stages(markup)["bài trong kho"] == ("plain", "29")
    assert "bài mới đã index" not in markup


def test_ingest_card_blocked_at_the_batch_gate():
    reason = 'the new batch failed freshness SLA (83% <older> than 180 days & "limit" 25%)'
    result = IngestResult(
        topic="vla <robots>",
        published_since="2025-01-01",
        fetched=6,
        batch_rows=6,
        batch_gate_passed=False,
        batch_stale_ratio=0.83,
        indexed=False,
        blocked_reason=reason,
    )
    markup = ui.ingest_card(result)

    assert markup.startswith('<div class="d10-ingest d10-ingest--blocked">')
    assert f'<span class="d10-verdict" style="color:{SIGNAL["problem"]}">BỊ CHẶN</span>' in markup
    assert "Không nạp gì, kho giữ nguyên. Lý do: the new batch failed freshness SLA (83% &lt;older&gt; than 180 days &amp; &quot;limit&quot; 25%)" in markup
    assert "<older>" not in markup and "vla &lt;robots&gt;" in markup
    assert stages(markup) == {
        "từ Crossref": ("plain", "6"),
        "sau làm sạch": ("plain", "6"),
        "bị cách ly": ("plain", "0"),
        "gate lô mới": ("bad", "FAIL"),
        "bài mới": ("skip", "—"),
        "gate kho gộp": ("skip", "—"),
        "bài trong kho": ("skip", "—"),
    }, "the stages after the failed gate were never reached"


def test_ingest_card_blocked_before_anything_was_fetched():
    result = IngestResult(topic="vla robots", published_since="2026-03-29", blocked_reason="Crossref could not be reached (ConnectionError)")
    found = stages(ui.ingest_card(result))
    assert found["từ Crossref"] == ("bad", "0")
    assert found["sau làm sạch"] == ("skip", "0")
    assert found["gate lô mới"] == ("skip", "—")


def test_ingest_card_blocked_at_the_merged_gate():
    result = IngestResult(
        topic="vla robots",
        published_since="2027-01-01",
        fetched=5,
        batch_rows=5,
        batch_gate_passed=True,
        merged_gate_passed=False,
        total_papers=24,
        blocked_reason="the merged collection would fail freshness SLA",
    )
    found = stages(ui.ingest_card(result))
    assert found["gate lô mới"] == ("ok", "PASS")
    assert found["bài mới"] == ("plain", "+0")
    assert found["gate kho gộp"] == ("bad", "FAIL")
    assert found["bài trong kho"] == ("plain", "24")


def test_ingest_card_lists_quarantined_rows_with_their_reasons():
    quarantined = [
        {"paper_id": "10.9999/junk", "title": "Sample complexity of embodied transformers", "reason": "junk symbols in summary ($${\\)"},
        {"paper_id": "10.9999/short", "title": "VLA <bot>", "reason": "title under 10 characters"},
    ]
    result = IngestResult(
        topic="vla robots",
        published_since="2026-03-29",
        fetched=7,
        batch_rows=7,
        quarantined=quarantined,
        batch_gate_passed=True,
        new_papers=5,
        merged_gate_passed=True,
        total_papers=29,
        indexed=True,
    )
    markup = ui.ingest_card(result)

    assert stages(markup)["bị cách ly"] == ("warn", "2")
    assert "<summary>2 bài bị cách ly</summary>" in markup
    assert "<li><code>10.9999/junk</code> junk symbols in summary ($${\\)<br><span>Sample complexity of embodied transformers</span></li>" in markup
    assert "<li><code>10.9999/short</code> title under 10 characters<br><span>VLA &lt;bot&gt;</span></li>" in markup


# --- gate statistics ---------------------------------------------------------------------------


def _tile_values(markup: str) -> dict[str, tuple[str, str]]:
    tiles = re.findall(r'<div class="rag-tile__k">(.*?)</div><div class="rag-tile__v">(.*?)</div><div class="rag-tile__s">(.*?)</div>', markup)
    return {label: (value, sub) for label, value, sub in tiles}


def test_gate_stat_tiles_with_runs():
    stats = {"runs": 3, "passed": 2, "blocked": 1, "fetched": 20, "quarantined": 4, "added": 5, "pass_rate": 2 / 3}
    assert _tile_values(ui.gate_stat_tiles(stats)) == {
        "Lần nạp": ("3", "67% qua gate"),
        "Qua gate": ("2", "được index"),
        "Bị chặn": ("1", "kho giữ nguyên"),
        "Bài lấy về": ("20", "từ Crossref"),
        "Bị cách ly": ("4", "20% số bài lấy về"),
        "Bài thêm vào kho": ("+5", "sau hai lần gate"),
    }


def test_gate_stat_tiles_before_any_run():
    tiles = _tile_values(ui.gate_stat_tiles(gate_stats([])))
    assert tiles["Lần nạp"] == ("0", "chưa chạy")
    assert tiles["Bị cách ly"] == ("0", "—"), "no division by zero fetched papers"
    assert tiles["Bài thêm vào kho"] == ("+0", "sau hai lần gate")


def test_reason_bars_without_counts_shows_the_empty_message():
    markup = ui.reason_bars("Lý do chặn", {}, tone="problem", empty="Chưa có lần <chặn> nào.")
    assert "Chưa có lần &lt;chặn&gt; nào." in markup
    assert "d10-reason__row" not in markup and ">Lý do chặn</div>" in markup


def test_reason_bars_scale_to_the_most_common_reason():
    counts = {"Freshness SLA (dữ liệu cũ)": 4, "Quá ít bài": 2, "Khác <x>": 1, "Hiếm": 0}
    markup = ui.reason_bars("Lý do chặn", counts, tone="warning", empty="unused")

    rows = re.findall(r'<div class="d10-reason__row"><span>(.*?)</span><span class="d10-fresh__bar"><i style="width:([0-9.]+)%;background:([^"]+)"></i></span><span class="d10-fresh__v">(\d+)</span></div>', markup)
    assert rows == [
        ("Freshness SLA (dữ liệu cũ)", "100.0", SIGNAL["warning"], "4"),
        ("Quá ít bài", "50.0", SIGNAL["warning"], "2"),
        ("Khác &lt;x&gt;", "25.0", SIGNAL["warning"], "1"),
        ("Hiếm", "4.0", SIGNAL["warning"], "0"),
    ], "widths are count / top, with a 4% floor so a bar stays visible"
    assert "unused" not in markup


def test_gate_stat_line_before_any_run():
    assert ui.gate_stat_line(gate_stats([])) == '<div class="d10-mode">Gate live: chưa có lần nạp nào.</div>'


def test_gate_stat_line_with_runs():
    line = ui.gate_stat_line({"runs": 3, "passed": 2, "blocked": 1, "quarantined": 4, "added": 5})
    assert line.startswith('<div class="d10-mode">Gate live: 3 lần nạp, ')
    assert f'<span style="color:{SIGNAL["pass"]}">2 qua</span>' in line
    assert f'<span style="color:{SIGNAL["problem"]}">1 chặn</span>' in line
    assert line.endswith("4 bài cách ly, +5 bài vào kho.</div>")


# --- ingest_history_table ----------------------------------------------------------------------


def _history_rows(markup: str) -> list[list[str]]:
    body = markup.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [re.findall(r"<td[^>]*>(.*?)</td>", row) for row in re.findall(r"<tr>(.*?)</tr>", body)]


def test_ingest_history_table_formats_time_and_verdicts():
    history = [
        {"at": "20260925T101530123456", "topic": "vla <robots>", "fetched": 7, "quarantined": [{}, {}], "indexed": True, "new_papers": 5, "total_papers": 29},
        {"at": "20260925T091500", "topic": "old stuff", "fetched": 6, "quarantined": None, "indexed": False, "new_papers": 4, "total_papers": 24,
         "blocked_reason": "the new batch failed freshness SLA (83% <old>)"},
        {"at": "2026", "topic": "short stamp"},
    ]
    rows = _history_rows(ui.ingest_history_table(history))

    assert len(rows) == 3
    first, blocked, short = rows
    assert first[0] == "10:15:30" and first[1] == "vla &lt;robots&gt;"
    assert first[2:4] == ["7", "2"] and first[5:7] == ["+5", "29"]
    assert f'color:{SIGNAL["pass"]}">NẠP</span>' in first[4] and first[7] == ""
    assert blocked[0] == "09:15:00"
    assert f'color:{SIGNAL["problem"]}">CHẶN</span>' in blocked[4]
    assert blocked[3] == "0" and blocked[5] == "+0", "a blocked run added nothing, whatever its log says"
    assert blocked[7] == "the new batch failed freshness SLA (83% &lt;old&gt;)"
    assert short[0] == "2026" and short[2:4] == ["0", "0"] and "CHẶN" in short[4]


def test_ingest_history_table_without_runs_keeps_its_header():
    markup = ui.ingest_history_table([])
    assert "<th>Giờ (UTC)</th>" in markup and "<tbody></tbody>" in markup


# --- source_list and out_of_scope_card ---------------------------------------------------------


def _source(number: int, score=None, via=None) -> dict:
    return {
        "paper_id": f"10.1/{number}",
        "title": f"Paper <{number}>",
        "authors_joined": "Ada Lovelace",
        "published": "2026-06-01",
        "summary": "A summary.",
        "abs_url": f"https://doi.org/10.1/{number}",
        "score": score,
        "via": via,
    }


def test_source_list_labels_each_retrieval_path():
    markup = ui.source_list([_source(1, 0.8123, "cosine"), _source(2, None, "filter"), _source(3, None, "exact"), _source(4, 0.4, "cosine")], turn=3)

    scores = re.findall(r'<div class="rag-src__score"><b>(.*?)</b><span>(.*?)</span></div>', markup)
    assert scores == [("0.812", "COSINE"), ("lọc", "METADATA"), ("exact", "LOOKUP"), ("0.400", "COSINE")]
    assert re.findall(r'id="(src-3-\d)"', markup) == ["src-3-1", "src-3-2", "src-3-3", "src-3-4"]
    assert "Paper &lt;1&gt;" in markup and "Paper <1>" not in markup
    widths = re.findall(r'<div class="rag-src__bar"><i style="width:([0-9.]+)%"></i></div>', markup)
    assert widths == ["100.0", "100.0", "100.0", "16.0"], "the best score fills the bar, the worst sits at the 16% floor"


def test_source_list_dims_papers_the_answer_did_not_cite():
    markup = ui.source_list([_source(1, 0.8, "cosine"), _source(2, None, "filter")], turn=1, cited={"10.1/1"})
    assert markup.count("d10-src--unused") == 1 and markup.count("đã đọc, không trích dẫn") == 1
    assert ui.source_list([], turn=1) == ""


def test_out_of_scope_card_without_topics():
    markup = ui.out_of_scope_card("Kho không có bài về chủ đề này.", ["semantic_search_papers(quantum)"], 0.2134, [], papers=44)
    assert "Kho có 44 bài." in markup and "về:" not in markup
    assert "Agent đã tìm (semantic_search_papers(quantum)) nhưng không bài nào đủ liên quan, cosine cao nhất 0.213." in markup


def test_out_of_scope_card_with_topics_and_no_search():
    markup = ui.out_of_scope_card("Không có.", [], None, ["RAG", "data <quality>"], papers=29)
    assert "Kho có 29 bài về: RAG, data &lt;quality&gt;." in markup
    assert "Agent đã tìm (không gọi công cụ)" in markup and "không có kết quả" in markup


@pytest.mark.parametrize("papers", [24, 44])
def test_out_of_scope_card_reports_the_collection_size_it_is_given(papers):
    assert f"Kho có {papers} bài." in ui.out_of_scope_card("x", ["s"], 0.1, [], papers=papers)
