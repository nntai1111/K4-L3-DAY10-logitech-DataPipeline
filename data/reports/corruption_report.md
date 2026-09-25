# Báo Cáo Đối Chiếu 3 Trạng Thái: Baseline vs Corrupted vs Repaired

> **Mục tiêu:** Chứng minh hiện tượng Silent Failure (AI nói dối khi dữ liệu bẩn) và năng lực tự phục hồi dữ liệu (Idempotent Repair).

---

## 1. Bảng So Sánh Chỉ Số Định Lượng (3 Trạng Thái)

| Chỉ số Đánh Giá (Metric) | 🟢 Baseline (Sạch) | 🔴 Corrupted (Bẩn) | 🔵 Repaired (Đã Sửa) | Xu Hướng Phục Hồi |
|:---|:---:|:---:|:---:|:---:|
| **Retrieval Hit Rate** | `1.00` | `0.11` | `1.00` | 📈 Phục hồi 100% |
| **Mean Token F1** | `0.38` | `0.07` | `0.38` | 📈 Phục hồi 100% |
| **LLM Judge Accuracy** | `0.22` | `0.00` | `0.22` | 📈 Phục hồi 100% |
| **Mean Judge Score (1-5)** | `2.11` | `1.11` | `2.22` | 📈 Phục hồi 100% |
| **GX 1.x Quality Check** | `PASS` | `FAIL` (Báo động) | `PASS` | 🛡️ Quality Gate Hoạt Động |
| **Freshness SLA (`is_fresh`)** | `True` | `False` | `True` | 🔄 Đạt Chuẩn SLA |

---

## 2. Phân Tích Hiện Tượng Silent Failure & Tự Phục Hồi
- **Khi dữ liệu bị tiêm 6 lỗi (Corrupted):** Data Quality Gate (Great Expectations 1.x) lập tức gióng chuông cảnh báo `FAIL`. RAG Agent sụt giảm chất lượng câu trả lời nghiêm trọng (Silent Failure).
- **Khi kích hoạt Idempotent Repair:** Pipeline tự động tái tạo dữ liệu sạch từ bản lưu trữ thô (`crossref_records.json`), phục hồi chỉ số về mức ban đầu.
