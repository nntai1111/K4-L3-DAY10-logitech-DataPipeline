# Báo cáo Pha 1 — Baseline

Sinh tự động bởi `script/run_phase1.py` lúc 2026-09-25 08:39 UTC. `run_date` = **2026-09-25** (mọi `age_days` tính theo ngày này).

## 1. Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Nguồn | Crossref REST API |
| Chế độ lấy dữ liệu | snapshot |
| Query | `agentic retrieval augmented generation large language model` |
| Filter | `from-pub-date:2026-03-29,has-abstract:true` |
| Số record raw | 24 |
| Số dòng sau làm sạch | 24 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| ChromaDB collection | `papers-baseline` (top_k = 4) |
| LLM judge | `gemini` / `gemini-3.5-flash-lite` |

## 2. Chỉ số đánh giá trên dữ liệu sạch

| Chỉ số | Giá trị |
| --- | --- |
| Số câu hỏi | 10 |
| Retrieval hit rate | 1.000 |
| Mean token F1 | 1.000 |
| Judge accuracy | 1.000 |
| Mean judge score (1–5) | 5.000 |
| Verdict do LLM chấm / heuristic dự phòng | 10 / 0 |

Theo loại câu hỏi:

| Loại | Số câu | Hit rate | Token F1 |
| --- | ---: | ---: | ---: |
| authors | 3 | 1.000 | 1.000 |
| categories | 2 | 1.000 | 1.000 |
| date | 2 | 1.000 | 1.000 |
| summary | 3 | 1.000 | 1.000 |

## 3. Quality gate (Great Expectations 1.x)

Kết quả GX: **PASS** — 8/8 expectation đạt. Gate tổng (GX + freshness): **PASS**.

| Expectation | Tầng | Baseline |
| --- | --- | --- |
| `expect_table_row_count_to_be_between` | required | PASS |
| `expect_column_values_to_not_be_null(paper_id)` | required | PASS |
| `expect_column_values_to_not_be_null(title)` | required | PASS |
| `expect_column_values_to_not_be_null(text_for_embedding)` | required | PASS |
| `expect_column_values_to_be_unique(paper_id)` | required | PASS |
| `expect_column_value_lengths_to_be_between(summary)` | required | PASS |
| `expect_column_value_lengths_to_be_between(title)` | extra | PASS |
| `expect_column_values_to_not_match_regex(summary)` | extra | PASS |
| Freshness SLA (≤ 25% dòng quá hạn) | sla | PASS (1/24 dòng > 180 ngày) |

## 4. Freshness SLA

| Thuộc tính | Giá trị |
| --- | --- |
| Bài mới nhất | 2026-07-22 |
| Bài cũ nhất | 2026-03-28 |
| Số dòng quá 180 ngày | 1 / 24 (4.2%) |
| Tuổi trung vị | 110.5 ngày |
| Kết luận | Tươi (ngưỡng: tối đa 25%) |

## 5. Artifact đã sinh

- `data/raw/crossref_response.json`
- `data/raw/crossref_records.json`
- `data/clean/papers_clean.csv`
- `data/clean/papers_clean.json`
- `data/embeddings/papers_embeddings.json`
- `data/eval/test_set.json`
- `data/quality/baseline_quality_report.json`
- `data/quality/freshness_report.json`
- `data/results/baseline_metrics.json`
- `data/results/baseline_answers.json`
- `data/results/agent_demo_answers.json`
- `data/results/run_context.json`
- `data/reports/phase1_report.md`
