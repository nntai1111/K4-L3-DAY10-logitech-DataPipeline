# Báo cáo đối chiếu 3 trạng thái — Baseline vs Corrupted vs Repaired

Sinh tự động bởi `script/run_corruption_flow.py` lúc 2026-09-25 08:42 UTC. Cả ba trạng thái dùng chung `data/eval/test_set.json` và cùng `run_date`.

## 1. Kết luận nhanh

- **Silent failure:** trên dữ liệu bẩn, hit rate 1.00 → 0.80 và token F1 1.00 → 0.80, nhưng pipeline không báo lỗi gì và agent vẫn trả lời mọi câu.
- **Quality gate:** GX FAIL trên dữ liệu bẩn (4 expectation fail), freshness FAIL. Gate tổng: FAIL.
- **Repair:** hit rate 1.00, token F1 1.00; gate PASS.
- **Idempotent:** bảng sau repair trùng khớp bảng baseline (sha256 `18f784380c172a51…`); trùng lần chạy trước.

## 2. Chỉ số RAG

| Chỉ số | Baseline | Corrupted | Repaired | Δ Corrupted | Δ Repaired |
| --- | ---: | ---: | ---: | ---: | ---: |
| Số câu hỏi | 10 | 10 | 10 | — | — |
| Retrieval hit rate | 1.000 | 0.800 | 1.000 | -0.200 | 0.000 |
| Mean token F1 | 1.000 | 0.800 | 1.000 | -0.200 | 0.000 |
| Judge accuracy | 1.000 | 0.800 | 1.000 | -0.200 | 0.000 |
| Mean judge score (1–5) | 5.000 | 4.200 | 5.000 | -0.800 | 0.000 |
| Verdict LLM / heuristic | 10 / 0 | 10 / 0 | 10 / 0 | — | — |

## 3. Quality gate và freshness

| Expectation | Tầng | Baseline | Corrupted | Repaired |
| --- | --- | --- | --- | --- |
| `expect_table_row_count_to_be_between` | required | PASS | PASS | PASS |
| `expect_column_values_to_not_be_null(paper_id)` | required | PASS | PASS | PASS |
| `expect_column_values_to_not_be_null(title)` | required | PASS | PASS | PASS |
| `expect_column_values_to_not_be_null(text_for_embedding)` | required | PASS | PASS | PASS |
| `expect_column_values_to_be_unique(paper_id)` | required | PASS | FAIL (8 dòng lỗi) | PASS |
| `expect_column_value_lengths_to_be_between(summary)` | required | PASS | FAIL (3 dòng lỗi) | PASS |
| `expect_column_value_lengths_to_be_between(title)` | extra | PASS | FAIL (3 dòng lỗi) | PASS |
| `expect_column_values_to_not_match_regex(summary)` | extra | PASS | FAIL (3 dòng lỗi) | PASS |
| Freshness SLA (≤ 25% dòng quá hạn) | sla | PASS (1/24 dòng > 180 ngày) | FAIL (13/24 dòng > 180 ngày) | PASS (1/24 dòng > 180 ngày) |

## 4. Sáu kịch bản tiêm lỗi

Seed `42`; 24 dòng vào, 24 dòng ra. Năm kịch bản sau bước bỏ bài nhắm vào các nhóm dòng không trùng nhau; riêng `duplicate_rows` nhân bản dòng bất kỳ, nên có thể chồng lên một kịch bản khác.

| Kịch bản | Số dòng | Mô tả | Bị phát hiện bởi | Câu hỏi bị ảnh hưởng |
| --- | ---: | --- | --- | --- |
| `drop_latest_records` | 4 | Bỏ 4 bài xuất bản gần nhất (mất dữ liệu tươi). | Không expectation nào bắt được; chỉ lộ ra qua bài mới nhất lùi từ 2026-07-22 về 2026-06-12 | eval_009, eval_010 |
| `blank_summary` | 3 | Xóa trắng summary thành chuỗi rỗng (bộ cào trả về rỗng). | `expect_column_value_lengths_to_be_between(summary)` — đã bắt | — |
| `inject_text_noise` | 3 | Chèn một cụm ký tự rác sau mỗi 3 từ của summary. | `expect_column_values_to_not_match_regex(summary)` — đã bắt | eval_002 |
| `truncate_title` | 3 | Cắt tiêu đề còn 7 ký tự đầu. | `expect_column_value_lengths_to_be_between(title)` — đã bắt | eval_006 |
| `stale_date` | 8 | Lùi ngày xuất bản 365 ngày, tính lại age_days. | Freshness SLA — đã bắt | eval_004, eval_005, eval_007, eval_008 |
| `duplicate_rows` | 4 | Nhân bản 4 dòng, trùng paper_id. | `expect_column_values_to_be_unique(paper_id)` — đã bắt | eval_001, eval_005 |

## 5. Từng câu hỏi

| ID | Loại | Tài liệu bị tác động bởi | Hit B / C / R | Token F1 B / C / R |
| --- | --- | --- | --- | --- |
| eval_001 | summary | duplicate_rows | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_002 | authors | inject_text_noise | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_003 | date | — | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_004 | categories | stale_date | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_005 | summary | duplicate_rows, stale_date | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_006 | authors | truncate_title | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_007 | date | stale_date | ✓ / ✓ / ✓ | 1.00 / 0.00 / 1.00 |
| eval_008 | categories | stale_date | ✓ / ✓ / ✓ | 1.00 / 1.00 / 1.00 |
| eval_009 | summary | drop_latest_records | ✓ / ✗ / ✓ | 1.00 / 0.00 / 1.00 |
| eval_010 | authors | drop_latest_records | ✓ / ✗ / ✓ | 1.00 / 1.00 / 1.00 |

## 6. Idempotent repair

- Nguồn phục hồi: `data/raw/crossref_records.json`, làm sạch lại bằng đúng `build_clean_dataframe` với `run_date` = 2026-09-25.
- Collection `papers-repaired` được xóa và tạo lại mỗi lần chạy, nên không còn vector cũ sót lại.
- sha256 bảng baseline: `18f784380c172a51b49d6c79254bcb5b7c0a871dd27c92876a256b07134d7d84`
- sha256 bảng repaired: `18f784380c172a51b49d6c79254bcb5b7c0a871dd27c92876a256b07134d7d84`
- Repair được kích hoạt tự động vì gate fail trên dữ liệu bẩn.
- sha256 lần chạy trước: `18f784380c172a51b49d6c79254bcb5b7c0a871dd27c92876a256b07134d7d84` → trùng khớp.
