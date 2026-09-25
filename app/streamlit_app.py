"""Day 10 research assistant and data-observability page.

    streamlit run app/streamlit_app.py

Tab 1 asks a tool-using agent about the indexed papers, on the collection picked in the
sidebar. Tab 2 puts one question to the clean, corrupted and repaired collections side by
side, which is the silent failure the lab is about. Tab 3 reads the pipeline's artifacts and
shows the three-state comparison, the quality gate and freshness.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import altair as alt
import pandas as pd
import streamlit as st

from core.config import load_settings
from core.utils import read_json
from evaluation.metrics import _token_f1 as token_f1
from observability.reporting import SCENARIO_DETECTORS
from retrieval.qa import answer_question
from data import load_artifacts
from demo_cases import build_demo_cases, corpus_topics, duplicate_count
from research import COLLECTION_FILES, ask_agent, ask_extractive, build_research_agent, llm_available, load_index
from ui import components as ui
from ui.theme import COLORS, SIGNAL, inject_css

st.set_page_config(page_title="Day 10 Research", page_icon=":material/menu_book:", layout="wide")
inject_css()

EXAMPLE_QUESTIONS = [
    "Which papers propose freshness SLAs for LLM knowledge bases?",
    "How can a RAG pipeline detect silent data failures?",
    "Who studied ghost vectors in dense retrieval?",
]
DETECTOR_TEXT = {
    "freshness_sla": "Freshness SLA",
    None: "Không expectation nào",
}


@st.cache_resource(show_spinner=False)
def get_settings():
    return load_settings()


@st.cache_resource(show_spinner="Đang nạp ChromaDB và mô hình embedding...")
def get_index(state: str):
    return load_index(get_settings(), state)


@st.cache_resource(show_spinner=False)
def get_agent(state: str):
    return build_research_agent(get_settings(), get_index(state))


settings = get_settings()
artifacts = load_artifacts(settings)
llm_ok, llm_note = llm_available(settings)

# --- sidebar ------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<p class="rag-panel-title">Cài đặt</p>', unsafe_allow_html=True)
    collection = st.segmented_control(
        "Kho dữ liệu cho trợ lý",
        options=list(COLLECTION_FILES),
        format_func=lambda key: COLLECTION_FILES[key][0],
        default="repaired",
        key="collection",
        help="Hỏi cùng một câu trên dữ liệu sạch, dữ liệu bẩn và dữ liệu đã sửa để thấy silent failure.",
    ) or "repaired"
    # The assistant always answers with the LLM agent. Extractive answers appear only as a
    # labelled fallback when the LLM is missing or errors, so the page never goes blank.
    st.caption(f"Agent LLM: {llm_note}" if llm_ok else f"LLM chưa sẵn sàng ({llm_note}). Tạm trả lời bằng trích xuất.")
    if st.button("Xóa hội thoại", icon=":material/restart_alt:", use_container_width=True):
        st.session_state.turns = []
    st.divider()
    st.markdown('<div class="rag-label">Bảng màu</div>', unsafe_allow_html=True)
    st.markdown(ui.signal_legend(), unsafe_allow_html=True)

# --- header -------------------------------------------------------------------------------
context = artifacts.run_context or {}
status = [
    ("run_date", context.get("run_date", "chưa chạy"), None),
    ("Nguồn", f"Crossref {context.get('source_mode', '?')}, {context.get('clean_rows', '?')} bài", None),
]
for name in ("baseline", "corrupted", "repaired"):
    if name in artifacts.states:
        passed = artifacts.states[name]["quality"]["gate_passed"]
        status.append((f"Gate {name}", "PASS" if passed else "FAIL", SIGNAL["pass"] if passed else SIGNAL["problem"]))
st.markdown(
    ui.header(
        "Kho bài báo RAG, có trạm kiểm soát dữ liệu",
        "Crossref vào, làm sạch, Great Expectations chặn dữ liệu xấu, ChromaDB phục vụ trợ lý nghiên cứu.",
        status,
    ),
    unsafe_allow_html=True,
)

research_tab, failure_tab, observability_tab = st.tabs(["Trợ lý nghiên cứu", "Silent failure", "Quan sát dữ liệu"])

# --- research assistant -------------------------------------------------------------------
with research_tab:
    st.session_state.setdefault("turns", [])
    chat_column, source_column = st.columns([3, 2], gap="large")

    with chat_column:
        # An example button queues its question and reruns, so the empty state is gone on the
        # run that answers it instead of lingering above the first reply.
        prompt = st.chat_input("Hỏi về các bài báo trong kho...") or st.session_state.pop("queued_question", None)
        if not st.session_state.turns and not prompt:
            st.markdown(
                ui.empty_state("Chưa có câu hỏi", "Hỏi bằng tiếng Việt hoặc tiếng Anh. Trợ lý chỉ trả lời từ 24 bài đã index."),
                unsafe_allow_html=True,
            )
            for number, example in enumerate(EXAMPLE_QUESTIONS):
                if st.button(example, key=f"example-{number}", use_container_width=True):
                    st.session_state.queued_question = example
                    st.rerun()

        if prompt:
            index = get_index(collection)
            with st.spinner("Đang tìm trong kho bài báo..."):
                if llm_ok:
                    try:
                        answer = ask_agent(get_agent(collection), index, prompt)
                    except Exception as error:  # quota, network, provider errors
                        answer = ask_extractive(settings, index, prompt, error=f"{type(error).__name__}: {str(error)[:180]}")
                else:
                    answer = ask_extractive(settings, index, prompt)
            st.session_state.turns.append({"collection": collection, "answer": answer})

        for turn_number, turn in enumerate(st.session_state.turns, start=1):
            answer = turn["answer"]
            st.markdown(ui.user_bubble(answer.question), unsafe_allow_html=True)
            if answer.error:
                st.markdown(
                    ui.banner(f"LLM lỗi, đã chuyển sang chế độ trích xuất: <code>{ui.esc(answer.error)}</code>", kind="warn"),
                    unsafe_allow_html=True,
                )
            if answer.mode == "agent" and not ui.cited_dois(answer.answer):
                # The agent searched and found nothing it could cite: say so, don't dress it as an answer.
                best_score = max((source["score"] for source in answer.sources if source.get("score") is not None), default=None)
                st.markdown(ui.out_of_scope_card(answer.answer, answer.tool_calls, best_score, corpus_topics(settings)), unsafe_allow_html=True)
            else:
                st.markdown(ui.answer_card(answer.answer, answer.sources, turn_number), unsafe_allow_html=True)
            mode = "agent + công cụ tìm kiếm" if answer.mode == "agent" else "trích xuất, không LLM"
            st.markdown(
                f'<div class="d10-mode">Kho {COLLECTION_FILES[turn["collection"]][0]}, {mode}, {len(answer.sources)} bài được đọc.</div>'
                + ui.tool_calls(answer.tool_calls),
                unsafe_allow_html=True,
            )

    with source_column:
        st.markdown(ui.section_label("Nguồn", note="bài được trích dẫn; bài mờ là đã đọc nhưng không dùng"), unsafe_allow_html=True)
        if st.session_state.turns:
            latest = st.session_state.turns[-1]["answer"]
            if latest.sources:
                st.markdown(
                    ui.source_list(latest.sources, turn=len(st.session_state.turns), cited=ui.cited_dois(latest.answer)),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(ui.empty_state("Không có nguồn", "Công cụ tìm kiếm không trả về bài nào cho câu này."), unsafe_allow_html=True)
        else:
            st.markdown(ui.empty_state("Nguồn hiện ở đây", "Mỗi bài có DOI, ngày xuất bản và điểm cosine."), unsafe_allow_html=True)

# --- observability ------------------------------------------------------------------------
def _detector_html(scenario_name: str, corrupted_quality: dict) -> str:
    detector = SCENARIO_DETECTORS.get(scenario_name)
    if detector is None:
        return f'<span style="color:{SIGNAL["problem"]}">Không expectation nào bắt được</span>'
    if detector == "freshness_sla":
        caught = not corrupted_quality["freshness"]["is_fresh"]
    else:
        item = next((item for item in corrupted_quality["expectations"] if f"{item['expectation']}({item['column']})" == detector), None)
        caught = item is not None and not item["success"]
    tone = "pass" if caught else "problem"
    label = DETECTOR_TEXT.get(detector, detector)
    return f'<span style="color:{SIGNAL[tone]}">{"Đã bắt" if caught else "Không bắt"}</span><br><code>{ui.esc(label)}</code>'


def _age_chart() -> alt.Chart:
    frames = []
    for name, path in (("Baseline", settings.paths.clean_json), ("Corrupted", settings.paths.corrupted_clean_json), ("Repaired", settings.paths.repaired_clean_json)):
        rows = pd.DataFrame(read_json(path))[["paper_id", "title", "published", "age_days"]]
        frames.append(rows.assign(state=name))
    ages = pd.concat(frames, ignore_index=True)
    ages["freshness"] = ages["age_days"].map(lambda days: "quá 180 ngày" if days > settings.freshness_threshold_days else "còn tươi")
    points = (
        alt.Chart(ages)
        .mark_circle(size=70, opacity=0.8)
        .encode(
            x=alt.X("age_days:Q", title="Tuổi bài báo (ngày)"),
            y=alt.Y("state:N", title=None, sort=["Baseline", "Corrupted", "Repaired"]),
            yOffset=alt.YOffset("jitter:Q"),
            color=alt.Color(
                "freshness:N",
                scale=alt.Scale(domain=["còn tươi", "quá 180 ngày"], range=[SIGNAL["pass"], SIGNAL["warning"]]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=["title:N", "published:N", "age_days:Q", "state:N"],
        )
        .transform_calculate(jitter="random()")
    )
    threshold = alt.Chart(pd.DataFrame({"x": [settings.freshness_threshold_days]})).mark_rule(strokeDash=[4, 4], color=COLORS["muted"]).encode(x="x:Q")
    return (points + threshold).properties(height=220).configure_axis(labelColor=COLORS["muted"], titleColor=COLORS["muted"], gridColor=COLORS["border"]).configure_view(stroke=None)


with observability_tab:
    if not artifacts.comparison_ready:
        st.markdown(
            ui.empty_state(
                "Chưa đủ dữ liệu để so sánh",
                "Chạy python script/run_phase1.py rồi python script/run_corruption_flow.py, sau đó tải lại trang.",
            ),
            unsafe_allow_html=True,
        )
        if artifacts.missing:
            st.caption("Thiếu: " + ", ".join(artifacts.missing))
    else:
        states = artifacts.states
        st.markdown(ui.section_label("Ba trạng thái", note="cùng 10 câu hỏi, cùng run_date"), unsafe_allow_html=True)
        st.markdown(ui.state_cards(states), unsafe_allow_html=True)

        fallback_counts = [
            sum(1 for answer in states[name]["answers"] if answer["judge"]["reasoning"].startswith("Fallback heuristic judge"))
            for name in ("baseline", "corrupted", "repaired")
        ]
        if any(fallback_counts):
            st.markdown(
                ui.banner(
                    f"Judge dùng heuristic dự phòng cho {sum(fallback_counts)} trên {3 * len(states['baseline']['answers'])} câu "
                    "(LLM không sẵn sàng lúc chạy). Hit rate và token F1 không bị ảnh hưởng.",
                    kind="warn",
                ),
                unsafe_allow_html=True,
            )

        st.markdown(ui.section_label("Quality gate", note="Great Expectations 1.x, ephemeral context"), unsafe_allow_html=True)
        st.markdown(ui.gate_table(states), unsafe_allow_html=True)

        st.markdown(ui.section_label("Độ tươi dữ liệu", note="Freshness SLA"), unsafe_allow_html=True)
        st.markdown(ui.freshness_bars(states), unsafe_allow_html=True)
        with st.expander("Phân bố tuổi bài báo theo trạng thái"):
            st.altair_chart(_age_chart(), use_container_width=True)

        if artifacts.corruption_log:
            st.markdown(ui.section_label("Sáu kịch bản tiêm lỗi", note=f"seed {artifacts.corruption_log['seed']}"), unsafe_allow_html=True)
            detectors = {scenario["scenario"]: _detector_html(scenario["scenario"], states["corrupted"]["quality"]) for scenario in artifacts.corruption_log["scenarios"]}
            st.markdown(ui.scenario_table(artifacts.corruption_log, detectors), unsafe_allow_html=True)

        with st.expander("Kết quả từng câu hỏi"):
            answers_by_state = {name: states[name]["answers"] for name in ("baseline", "corrupted", "repaired")}
            st.markdown(ui.question_table(answers_by_state, artifacts.scenarios_by_paper()), unsafe_allow_html=True)

        if artifacts.repair:
            repair = artifacts.repair
            same = "trùng" if repair["repaired_matches_baseline"] else "KHÁC"
            st.markdown(
                ui.banner(
                    f"Repair đọc lại <code>{ui.esc(repair['source'])}</code> với run_date {ui.esc(repair['run_date'])}. "
                    f"Bảng sau repair {same} bảng baseline (sha256 <code>{ui.esc(repair['repaired_sha256'][:16])}</code>). "
                    + ("Kích hoạt tự động vì gate fail." if repair["auto_triggered"] else "Chạy thủ công."),
                ),
                unsafe_allow_html=True,
            )


# --- silent failure -----------------------------------------------------------------------
STATE_NAMES = ("baseline", "corrupted", "repaired")
SOURCE_MODES = {"scenario": "Theo kịch bản lỗi", "testset": "Câu hỏi trong test set", "free": "Tự nhập"}


@st.cache_resource(show_spinner="Đang chọn câu hỏi demo cho từng kịch bản...")
def get_demo_cases():
    return build_demo_cases(get_settings(), get_index("corrupted"))


def _compare_row(name: str, question: str, expected: dict | None, scenarios_by_paper: dict) -> dict:
    index = get_index(name)
    result = answer_question(question, settings=settings, index=index)
    top = index.lookup(result.retrieved_doc_ids[0]) if result.retrieved_doc_ids else None
    row = {
        "label": artifacts.states[name]["label"],
        "answer": result.answer,
        "source": top["metadata"] if top else None,
        "duplicates": duplicate_count(result.retrieved_doc_ids),
    }
    if expected:
        row["hit"] = any(doc_id in expected["ground_truth_doc_ids"] for doc_id in result.retrieved_doc_ids)
        row["f1"] = token_f1(expected["ground_truth"], result.answer)
        if name == "corrupted":
            row["touched"] = sorted({scenario for doc_id in expected["ground_truth_doc_ids"] for scenario in scenarios_by_paper.get(doc_id, [])})
    return row


def _agent_comparison(question: str) -> None:
    # Cached resources are resolved here, on Streamlit's own thread; only the three agent calls
    # run in parallel, which cuts the wait from about 33s to one call's time.
    agents = {name: (get_agent(name), get_index(name)) for name in STATE_NAMES}

    def ask(name: str):
        try:
            return ask_agent(*agents[name], question), None
        except Exception as error:  # quota, network, provider errors
            return None, error

    with st.spinner("Agent đang đọc cả ba kho..."), ThreadPoolExecutor(max_workers=3) as pool:
        replies = dict(zip(STATE_NAMES, pool.map(ask, STATE_NAMES)))
    baseline_reply = replies["baseline"][0]
    # Keyed container, so day10.css can undo the kit's sticky second column inside it.
    for column, name in zip(st.container(key="agent-compare").columns(3), STATE_NAMES):
        reply, error = replies[name]
        with column:
            st.markdown(ui.section_label(artifacts.states[name]["label"]), unsafe_allow_html=True)
            if error is not None:
                st.markdown(ui.banner(f"LLM lỗi: <code>{ui.esc(str(error)[:160])}</code>", kind="warn"), unsafe_allow_html=True)
                continue
            # Words the clean collection's agent did not say are highlighted.
            reference = baseline_reply.answer if baseline_reply and name != "baseline" else None
            turn = 900 + STATE_NAMES.index(name)
            st.markdown(ui.answer_card(reply.answer, reply.sources, turn=turn, compare_to=reference), unsafe_allow_html=True)
            st.markdown(ui.tool_calls(reply.tool_calls), unsafe_allow_html=True)


with failure_tab:
    if not settings.paths.eval_testset.exists() or not artifacts.comparison_ready:
        st.markdown(ui.empty_state("Chưa có dữ liệu so sánh", "Chạy cả hai script pipeline rồi tải lại trang."), unsafe_allow_html=True)
    else:
        st.markdown(
            ui.section_label("Cùng một câu hỏi, ba kho dữ liệu", note="chỉ truy xuất và trích xuất, không gọi LLM"),
            unsafe_allow_html=True,
        )
        mode = st.segmented_control(
            "Nguồn câu hỏi", options=list(SOURCE_MODES), format_func=SOURCE_MODES.get, default="scenario", key="failure_mode",
            label_visibility="collapsed",
        ) or "scenario"

        expected = None
        question = ""
        if mode == "scenario":
            cases = get_demo_cases()
            by_scenario = {case.scenario: case for case in cases}
            scenario = st.segmented_control(
                "Kịch bản", options=list(by_scenario), format_func=lambda key: by_scenario[key].label,
                default=cases[0].scenario, key="failure_scenario", label_visibility="collapsed",
            ) or cases[0].scenario
            case = by_scenario[scenario]
            st.markdown(f'<p class="d10-scenario-story">{ui.esc(case.story)}</p>', unsafe_allow_html=True)
            question = case.question
            expected = {"ground_truth": case.ground_truth, "ground_truth_doc_ids": [case.paper_id], "question_type": case.question_type}
            st.caption(f"Câu hỏi demo sinh từ corruption log, không dùng để tính điểm: {question}")
        elif mode == "testset":
            test_set = read_json(settings.paths.eval_testset)
            options = [f"{item['id']} · {item['question_type']} · {item['question']}" for item in test_set]
            choice = st.selectbox("Câu hỏi", options, label_visibility="collapsed")
            expected = test_set[options.index(choice)]
            question = expected["question"]
        else:
            question = st.text_input(
                "Câu hỏi của bạn",
                placeholder="Ví dụ: When was 'Freshness SLAs for Real-Time LLM Knowledge Augmentation' published?",
            )

        if question:
            if expected:
                st.markdown(ui.ground_truth_line(expected["question_type"], expected["ground_truth"]), unsafe_allow_html=True)
            scenarios_by_paper = artifacts.scenarios_by_paper()
            rows = [_compare_row(name, question, expected, scenarios_by_paper) for name in STATE_NAMES]
            st.markdown(
                ui.comparison_cards(rows, ground_truth=expected["ground_truth"] if expected else None),
                unsafe_allow_html=True,
            )
            st.caption(
                "Không kho nào báo lỗi. Câu trả lời trên dữ liệu bẩn vẫn trôi chảy và tự tin; "
                "chỉ quality gate ở tab Quan sát dữ liệu thấy dữ liệu có vấn đề."
            )
            if llm_ok and st.button("Hỏi agent trên cả ba kho", icon=":material/forum:", help="Tốn 3 lượt gọi LLM trở lên"):
                _agent_comparison(question)
