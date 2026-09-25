# Báo cáo Corruption & Repair — Đối chiếu 3 trạng thái

> Sinh tự động bởi `script/run_corruption_flow.py` lúc `2026-09-25T09:25:09.904006+00:00`. Cả 3 trạng thái được đánh giá trên **cùng một test set** (10 câu) và cùng cấu hình retrieval/LLM.

## Tóm tắt

- **Silent failure:** pipeline index và trả lời trên dữ liệu hỏng mà **không phát sinh lỗi nào**, nhưng hit rate `1.000 → 0.800` và token F1 `1.000 → 0.745`.
- **Observability phát hiện:** gate GX ❌ FAIL (7/12), failed checks: `paper_id_unique`, `summary_min_length`, `title_min_length`, `summary_no_noise`, `source_papers_present`; freshness ⚠️ STALE (31.8% stale). Phát hiện 6/6 kịch bản tiêm lỗi.
- **Repair:** dựng lại từ `data/raw/crossref_records.json` → gate ✅ PASS (12/12), freshness ✅ FRESH (4.2% stale), hit rate `1.000`, token F1 `1.000`. Idempotent: ✅; khớp baseline: ✅.

## 1. Bảng đối chiếu 3 trạng thái

| Metric / signal | Baseline | Corrupted | Repaired | Δ Corrupted − Baseline | Δ Repaired − Baseline | Mức phục hồi |
| --- | --- | --- | --- | --- | --- | --- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | -0.200 | +0.000 | 100% |
| `mean_token_f1` | 1.000 | 0.745 | 1.000 | -0.255 | +0.000 | 100% |
| `judge_accuracy` | 1.000 | 0.800 | 1.000 | -0.200 | +0.000 | 100% |
| `mean_judge_score` | 5.000 | 4.200 | 5.000 | -0.800 | +0.000 | 100% |
| Quality gate (GX 1.x) | ✅ PASS (12/12) | ❌ FAIL (7/12) | ✅ PASS (12/12) |  |  |  |
| Freshness SLA | ✅ FRESH (4.2% stale) | ⚠️ STALE (31.8% stale) | ✅ FRESH (4.2% stale) |  |  |  |
| Số dòng / paper_id duy nhất | 24 / 24 | 22 / 19 | 24 / 24 |  |  |  |
| Bài mới nhất (`latest_published`) | 2026-07-22 | 2026-06-12 | 2026-07-22 |  |  |  |
| Chế độ judge | 10 câu khớp nguyên văn đáp án (không cần gọi LLM) | LLM judge `gemini/gemini-3.5-flash-lite` chấm 5 câu, 5 lấy lại từ cache; 5 câu khớp nguyên văn đáp án (không cần gọi LLM) | 10 câu khớp nguyên văn đáp án (không cần gọi LLM) |  |  |  |

Mức phục hồi = (Repaired − Corrupted) / (Baseline − Corrupted); 100% nghĩa là trở về đúng baseline.

## 2. Quality gate theo từng expectation

| Check | Chiều | Baseline | Corrupted | Repaired | Bằng chứng (corrupted) |
| --- | --- | --- | --- | --- | --- |
| `schema_columns` | schema | ✅ | ✅ | ✅ |  |
| `row_count` | volume | ✅ | ✅ | ✅ |  |
| `paper_id_not_null` | completeness | ✅ | ✅ | ✅ |  |
| `title_not_null` | completeness | ✅ | ✅ | ✅ |  |
| `text_for_embedding_not_null` | completeness | ✅ | ✅ | ✅ |  |
| `paper_id_unique` | uniqueness | ✅ | ❌ | ✅ | 6 dòng vi phạm, vd `10.1145/3637528.3671824` |
| `summary_min_length` | validity | ✅ | ❌ | ✅ | 3 dòng vi phạm, vd `""` |
| `title_min_length` | validity | ✅ | ❌ | ✅ | 4 dòng vi phạm, vd `Advance` |
| `summary_no_noise` | validity | ✅ | ❌ | ✅ | 3 dòng vi phạm, vd `An %*%CLr extended empirical $*&rjn study on single @&&MqZ LLM ~@*f...` |
| `paper_id_is_doi` | validity | ✅ | ✅ | ✅ |  |
| `published_iso_date` | validity | ✅ | ✅ | ✅ |  |
| `source_papers_present` | completeness | ✅ | ❌ | ✅ | thiếu 5 paper, vd `10.1145/3637528.3671802` |

## 3. Freshness SLA

| Thuộc tính | Baseline | Corrupted | Repaired |
| --- | --- | --- | --- |
| Trạng thái | ✅ FRESH (4.2% stale) | ⚠️ STALE (31.8% stale) | ✅ FRESH (4.2% stale) |
| Dòng stale | 1 | 7 | 1 |
| Tổng dòng | 24 | 22 | 24 |
| Tỉ lệ stale | 0.042 | 0.318 | 0.042 |
| Bài mới nhất | 2026-07-22 | 2026-06-12 | 2026-07-22 |
| Bài cũ nhất | 2026-03-28 | 2025-03-28 | 2026-03-28 |
| Tuổi nhỏ nhất (ngày) | 65 | 105 | 65 |

## 4. Sáu kịch bản tiêm lỗi (`data/results/corruption_log.json`)

Seed `42` — 24 dòng sạch → 22 dòng hỏng (19 paper duy nhất).

| # | Kịch bản | Mô tả | Tham số | Dòng | Tín hiệu kỳ vọng | Đã phát hiện? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Drop latest records | Newest papers never reach the index (ingestion lost the freshest batch). | fraction=0.2 | 5 | `source_papers_present`, `freshness.latest_published` | ✅ `source_papers_present`, `freshness.latest_published` |
| 2 | Blank summary | Summary replaced by an empty string. | fraction=0.15 | 3 | `summary_min_length` | ✅ `summary_min_length` |
| 3 | Inject noise | Garbage symbol tokens inserted into the summary text. | fraction=0.15, word_probability=0.3, symbols=#@$%^&*~ | 3 | `summary_no_noise` | ✅ `summary_no_noise` |
| 4 | Truncate title | Title cut to its first 7 characters. | fraction=0.15, max_chars=7 | 3 | `title_min_length` | ✅ `title_min_length` |
| 5 | Stale date | Published date shifted back 365 days. | fraction=0.35, shift_days=365 | 7 | `freshness_sla` | ✅ `freshness_sla` |
| 6 | Duplicate rows | Rows appended a second time with the same paper_id. | fraction=0.15 | 3 | `paper_id_unique` | ✅ `paper_id_unique` |

Ví dụ trước/sau:

- Drop latest records: paper_id=`10.1145/3637528.3671812`, published=`2026-07-22`
- Blank summary: `Embedding quality checks directly into data pipelines enables fail-...` → `""`
- Inject noise: `An extended empirical study on single LLM is susceptible to confirm...` → `An %*%CLr extended empirical $*&rjn study on single @&&MqZ LLM ~@*f...`
- Truncate title: `Advanced Perspectives on Synthetic Corruption Testing: Stress-Testi...` → `Advance`
- Stale date: `2026-06-11` → `2025-06-11`
- Duplicate rows: paper_id=`10.1145/3637528.3671824`

## 5. Tác động lên từng câu hỏi

| id | Loại | Paper | Lỗi trên paper | Hit B/C/R | Token F1 B/C/R | Judge B/C/R |
| --- | --- | --- | --- | --- | --- | --- |
| eval_001 | summary | `Continuous Benchmark Evaluation for Enterp...` | drop_latest_records | ✅ / ❌ / ✅ | 1.00 / 0.74 / 1.00 | ✅ / ✅ / ✅ |
| eval_002 | authors | `Synthetic Corruption Testing: Stress-Testi...` | drop_latest_records | ✅ / ❌ / ✅ | 1.00 / 0.00 / 1.00 | ✅ / ❌ / ✅ |
| eval_003 | date | `Advanced Perspectives on Continuous Benchm...` | duplicate_rows | ✅ / ✅ / ✅ | 1.00 / 1.00 / 1.00 | ✅ / ✅ / ✅ |
| eval_004 | categories | `Advanced Perspectives on Chunking Strategi...` | duplicate_rows | ✅ / ✅ / ✅ | 1.00 / 1.00 / 1.00 | ✅ / ✅ / ✅ |
| eval_005 | summary | `Advanced Perspectives on Multi-Agent Conse...` | inject_noise | ✅ / ✅ / ✅ | 1.00 / 0.82 / 1.00 | ✅ / ✅ / ✅ |
| eval_006 | authors | `Advanced Perspectives on Evaluating Retrie...` | — | ✅ / ✅ / ✅ | 1.00 / 1.00 / 1.00 | ✅ / ✅ / ✅ |
| eval_007 | date | `Advanced Perspectives on Mitigating Ghost ...` | stale_date | ✅ / ✅ / ✅ | 1.00 / 0.00 / 1.00 | ✅ / ❌ / ✅ |
| eval_008 | categories | `Agentic Retrieval-Augmented Generation for...` | blank_summary | ✅ / ✅ / ✅ | 1.00 / 1.00 / 1.00 | ✅ / ✅ / ✅ |
| eval_009 | summary | `Semantic Layer Integration for Agentic Tex...` | inject_noise | ✅ / ✅ / ✅ | 1.00 / 0.89 / 1.00 | ✅ / ✅ / ✅ |
| eval_010 | authors | `Evaluating Retrieval Precision with Token ...` | stale_date | ✅ / ✅ / ✅ | 1.00 / 1.00 / 1.00 | ✅ / ✅ / ✅ |

## 6. Phân tích nguyên nhân → hệ quả

- **Drop latest records** → eval_001 (summary), eval_002 (authors): mất retrieval hit ở 2 câu (eval_001, eval_002); token F1 giảm ở 2 câu (trung bình −0.63); judge chuyển sang sai ở 1 câu (eval_002). Phát hiện bởi: `source_papers_present`, `freshness.latest_published`.
- **Blank summary** → eval_008 (categories): câu trả lời không đổi vì lỗi không làm sai trường dữ liệu mà câu hỏi sử dụng. Phát hiện bởi: `summary_min_length`.
- **Inject noise** → eval_005 (summary), eval_009 (summary): token F1 giảm ở 2 câu (trung bình −0.15). Phát hiện bởi: `summary_no_noise`.
- **Truncate title** (3 dòng): không trúng tài liệu nào của test set → benchmark không thấy lỗi này; chỉ lớp observability phát hiện (`title_min_length`).
- **Stale date** → eval_007 (date), eval_010 (authors): token F1 giảm ở 1 câu (trung bình −1.00); judge chuyển sang sai ở 1 câu (eval_007). Phát hiện bởi: `freshness_sla`.
- **Duplicate rows** → eval_003 (date), eval_004 (categories): câu trả lời không đổi vì lỗi không làm sai trường dữ liệu mà câu hỏi sử dụng. Phát hiện bởi: `paper_id_unique`.
- **Silent failure nguy hiểm nhất:** eval_001 — tài liệu đúng không còn trong top-k (hit ❌) nhưng câu trả lời vẫn được judge chấm là đúng, vì hệ thống lấy nội dung gần giống từ một paper khác. Metric chất lượng câu trả lời không bắt được lỗi này; chỉ retrieval hit và quality gate (`source_papers_present`) cho thấy dữ liệu đã mất.

Kết luận: benchmark chỉ bao phủ các paper nằm trong test set, nên có lỗi dữ liệu không làm đổi metric nào. Quality gate và freshness SLA kiểm tra **toàn bộ** dataset, nên phát hiện được cả những lỗi mà metric RAG không thấy.

## 7. Repair & tính idempotent

- **Kích hoạt:** tự động vì gate thất bại (`paper_id_unique`, `summary_min_length`, `title_min_length`, `summary_no_noise`, `source_papers_present`) và freshness `STALE`.
- **Nguồn phục hồi:** `data/raw/crossref_records.json`; kiểm tra lineage với `data/raw/crossref_response.json`: ✅ khớp.
- **Cách làm:** parse lại raw → áp đúng quy tắc cleaning của baseline → validate lại bằng gate → chỉ index khi gate đạt. Không vá tay dữ liệu hỏng, nên chạy lại bao nhiêu lần cũng ra cùng một dataset.

| Dataset | Fingerprint (SHA-256 nội dung) | Khớp baseline? |
| --- | --- | --- |
| Baseline clean (pha 1) | `a9364c4a312d857c…` | — |
| Corrupted | `556b513e476978ad…` | ❌ |
| Repair lần 1 | `a9364c4a312d857c…` | ✅ |
| Repair lần 2 | `a9364c4a312d857c…` | ✅ |

## 8. Artifacts

- Corruption log: `data/results/corruption_log.json`
- Corrupted dataset: `data/clean/papers_clean_corrupted.csv`
- Corrupted quality report: `data/quality/corrupted_quality_report.json`
- Corrupted freshness: `data/quality/corrupted_freshness_report.json`
- Corrupted metrics: `data/results/corrupted_metrics.json`
- Corrupted answers: `data/results/corrupted_answers.json`
- Repaired dataset: `data/clean/papers_clean_repaired.csv`
- Repaired quality report: `data/quality/repaired_quality_report.json`
- Repaired freshness: `data/quality/repaired_freshness_report.json`
- Repaired metrics: `data/results/repaired_metrics.json`
- Repaired answers: `data/results/repaired_answers.json`
- Repair log: `data/results/repair_log.json`
