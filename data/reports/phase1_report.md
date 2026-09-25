# Báo Cáo Baseline Pipeline (Pha 1) - Day 10 Data Observability

> **Ngày thực thi:** 2026-09-25 08:11:15 UTC  
> **Trạng thái luồng:** Baseline Data Pipeline End-to-End  

---

## 1. Nguồn Dữ Liệu Raw & Ingestion
- **Tổng số bản ghi tải về:** 24
- **Nguồn dữ liệu:** `Crossref REST API`
- **Truy vấn:** `agentic retrieval augmented generation large language model`
- **Data Lineage:** Bảo toàn tại `data/raw/crossref_response.json` và `crossref_records.json`.

---

## 2. Kiểm Định Chất Lượng (Data Quality Gate & Freshness SLA)
- **Great Expectations 1.x Validation:** `PASS`
- **Tỉ lệ bài báo quá hạn (> 180 ngày):** 4.2% (1/24 dòng)
- **Đánh giá độ tươi dữ liệu (`is_fresh`):** `FRESH`
- **Ngày công bố mới nhất:** `2026-07-22`
- **Ngày công bố cũ nhất:** `2026-03-28`

---

## 3. Chỉ Số Đánh Giá Baseline (Benchmark Metrics)
| Chỉ số (Metric) | Giá trị Baseline | Tiêu chuẩn đạt |
|:---|:---:|:---:|
| **Retrieval Hit Rate** | `1.00` | >= 0.70 |
| **Mean Token F1** | `0.38` | >= 0.50 |
| **LLM Judge Accuracy** | `0.22` | >= 0.70 |
| **Mean LLM Judge Score** | `2.11 / 5.0` | >= 3.5 |

---

## 4. Kết Luận Pha 1
Dữ liệu sạch đã qua trạm kiểm định Great Expectations 1.x thành công và được index vào ChromaDB collection `papers-baseline`. Các chỉ số nền (Baseline Benchmarks) đã được ghi nhận đầy đủ.
