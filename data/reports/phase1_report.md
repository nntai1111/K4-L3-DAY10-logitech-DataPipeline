# Báo cáo Pha 1 — Baseline Pipeline

> Sinh tự động bởi `script/run_phase1.py` lúc `2026-09-25T09:24:54.975444+00:00`. Mọi số liệu bên dưới được đọc từ artifact của chính lần chạy này.

## Tóm tắt

- **Quality gate (Great Expectations 1.x):** ✅ PASS (12/12) — dữ liệu chỉ được index sau khi gate đạt.
- **Freshness SLA:** ✅ FRESH (4.2% stale) — 1/24 bài có `age_days > 180` (ngưỡng cảnh báo 25%).
- **RAG baseline:** hit rate `1.000`, token F1 `1.000`, judge accuracy `1.000`, judge score `5.00`/5 trên 10 câu hỏi.

## 1. Nguồn dữ liệu & lineage

| Thuộc tính | Giá trị |
| --- | --- |
| Nguồn | Crossref REST API — `https://api.crossref.org/works` |
| Chế độ nạp | `snapshot` |
| Query | `agentic retrieval augmented generation large language model` |
| Filter (áp dụng khi gọi API live) | `from-pub-date:2026-03-29,has-abstract:true` |
| Số item trong payload / hợp lệ | 24 / 24 |
| Raw response (giữ nguyên byte) | `data/raw/crossref_response.json` |
| SHA-256 raw response | `d968be684bff7d7fc8245194e46544a3a3f477418437cce993bc17d4ecab5cc0` |
| Raw records (PaperRecord) | `data/raw/crossref_records.json` |

## 2. Làm sạch & mô hình dữ liệu

| Chỉ số | Giá trị |
| --- | --- |
| Run date (dùng tính `age_days`) | `2026-09-25T09:24:46.147974+00:00` |
| Bản ghi đầu vào | 24 |
| Loại do không hợp lệ | 0 |
| Loại do trùng `paper_id` | 0 |
| Số dòng sạch | 24 |

Quy tắc làm sạch:

1. Normalize whitespace in every text field; lowercase paper_id (DOI).
2. Deduplicate authors and categories while keeping their order; empty categories become 'Uncategorized'.
3. Drop rows without paper_id, with a title shorter than 8 chars, a summary shorter than 30 chars, or an unparseable published date.
4. Deduplicate by paper_id, keeping the most recently updated version.
5. age_days = (run_date - published).days; text_for_embedding = Title/Authors/Published/Categories/Summary.
6. Sort by published (newest first), then paper_id.

## 3. Data quality gate — Great Expectations 1.x

- Engine: great_expectations 1.18.0 (ephemeral context, pandas dataframe batch)
- Kết quả: ✅ PASS (12/12) · success_percent = 100.0%
- Kết quả GX gốc: `data/quality/gx/baseline_validation_result.json`

| Check | Expectation | Chiều chất lượng | Loại | Kết quả | Quan sát |
| --- | --- | --- | --- | --- | --- |
| `schema_columns` | expect_table_columns_to_match_set | schema | mở rộng | ✅ | 16 cột |
| `row_count` | expect_table_row_count_to_be_between | volume | bắt buộc | ✅ | 24 |
| `paper_id_not_null` | expect_column_values_to_not_be_null | completeness | bắt buộc | ✅ | 0/24 dòng vi phạm |
| `title_not_null` | expect_column_values_to_not_be_null | completeness | bắt buộc | ✅ | 0/24 dòng vi phạm |
| `text_for_embedding_not_null` | expect_column_values_to_not_be_null | completeness | bắt buộc | ✅ | 0/24 dòng vi phạm |
| `paper_id_unique` | expect_column_values_to_be_unique | uniqueness | bắt buộc | ✅ | 0/24 dòng vi phạm |
| `summary_min_length` | expect_column_value_lengths_to_be_between | validity | bắt buộc | ✅ | 0/24 dòng vi phạm |
| `title_min_length` | expect_column_value_lengths_to_be_between | validity | mở rộng | ✅ | 0/24 dòng vi phạm |
| `summary_no_noise` | expect_column_values_to_not_match_regex | validity | mở rộng | ✅ | 0/24 dòng vi phạm |
| `paper_id_is_doi` | expect_column_values_to_match_regex | validity | mở rộng | ✅ | 0/24 dòng vi phạm |
| `published_iso_date` | expect_column_values_to_match_regex | validity | mở rộng | ✅ | 0/24 dòng vi phạm |
| `source_papers_present` | expect_column_distinct_values_to_contain_set | completeness | mở rộng | ✅ | 24/24 source papers present |

## 4. Freshness SLA

| Thuộc tính | Giá trị |
| --- | --- |
| Trạng thái | ✅ FRESH (4.2% stale) |
| Ngưỡng tuổi | 180 ngày |
| Tỉ lệ stale tối đa | 25% |
| Số dòng stale | 1/24 (4.2%) |
| Bài mới nhất / cũ nhất | 2026-07-22 / 2026-03-28 |
| Tuổi nhỏ nhất / trung vị / lớn nhất | 65 / 110.5 / 181 ngày |
| Thông điệp | OK: 1/24 rows (4.2%) are older than 180 days, within the 25% SLA. |

## 5. Vector index

| Thuộc tính | Giá trị |
| --- | --- |
| Vector store | ChromaDB persistent `data/chroma` |
| Collection | `papers-baseline` |
| Số document | 24 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (normalize, cosine) |
| Retrieval top_k | 4 |
| Manifest | `data/embeddings/papers_embeddings.json` |

## 6. Kết quả đánh giá RAG (baseline)

Test set: `data/eval/test_set.json` — 10 câu, tái sử dụng bộ cố định; phân bố: `summary` 3, `authors` 3, `date` 2, `categories` 2.

| Metric | Giá trị |
| --- | --- |
| samples | 10 |
| `retrieval_hit_rate` | 1.000 |
| `mean_token_f1` | 1.000 |
| `judge_accuracy` | 1.000 |
| `mean_judge_score` | 5.000 |
| Chế độ judge | 10 câu khớp nguyên văn đáp án (không cần gọi LLM) |
| Ragas | Set RUN_RAGAS=1 to enable the slower Ragas pass. |

Theo loại câu hỏi:

| question_type | n | hit rate | token F1 | judge accuracy |
| --- | --- | --- | --- | --- |
| `summary` | 3 | 1.000 | 1.000 | 1.000 |
| `authors` | 3 | 1.000 | 1.000 | 1.000 |
| `date` | 2 | 1.000 | 1.000 | 1.000 |
| `categories` | 2 | 1.000 | 1.000 | 1.000 |

**Diễn giải:** baseline đạt mức trần là đúng kỳ vọng của thiết kế. `retrieval/qa.py` trích câu trả lời trực tiếp từ metadata của tài liệu top-1 (tra cứu chính xác theo tiêu đề trong dấu nháy đơn), còn ground truth của test set được sinh từ cùng các trường đó của dữ liệu sạch. Vì vậy baseline là mức tham chiếu (upper bound): mọi suy giảm ở pha corruption đều do dữ liệu, không phải do mô hình.

## 7. Demo QA agent (LangChain tool-calling)

- **Hỏi:** What is the main finding of the paper 'Continuous Benchmark Evaluation for Enterprise Retrieval Pipelines'?
  - **Đáp:** Based on the paper *"Continuous Benchmark Evaluation for Enterprise Retrieval Pipelines"* by Quang Le and Yen Vu, the main finding and contribution is that **static benchmarks fail to capture domain drift in enterprise knowledge bases**.   To address this challenge, the authors establish a **synthetic test generator** that automatically creates paired evaluation sets whenever new corpora are ingested, enabling continuous and dynamic benchmark evaluation for enterprise retrieval pipelines.
- **Hỏi:** Who authored the paper 'Synthetic Corruption Testing: Stress-Testing Vector Search Robustness'?
  - **Đáp:** The paper "Synthetic Corruption Testing: Stress-Testing Vector Search Robustness" was authored by **Kien Duong** and **Vy Ly**.
- **Hỏi:** What does the indexed corpus say about protein structure prediction with AlphaFold?
  - **Đáp:** Based on the indexed scholarly paper corpus, there are no indexed papers specifically discussing protein structure prediction or AlphaFold. The available papers in the corpus primarily focus on information retrieval, hybrid search architectures (combining BM25 and dense representations), continuous benchmark evaluation, and vector search robustness.

## 8. Artifacts

- Raw API response: `data/raw/crossref_response.json`
- Raw records: `data/raw/crossref_records.json`
- Ingestion manifest: `data/raw/ingestion_manifest.json`
- Clean CSV: `data/clean/papers_clean.csv`
- Clean JSON: `data/clean/papers_clean.json`
- Quality report: `data/quality/baseline_quality_report.json`
- Freshness report: `data/quality/freshness_report.json`
- Embedding manifest: `data/embeddings/papers_embeddings.json`
- Test set: `data/eval/test_set.json`
- Baseline metrics: `data/results/baseline_metrics.json`
- Baseline answers: `data/results/baseline_answers.json`
- Agent demo: `data/results/agent_demo_answers.json`
