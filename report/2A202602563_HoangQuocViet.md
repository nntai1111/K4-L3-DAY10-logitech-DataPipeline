# BÁO CÁO ĐÓNG GÓP CÁ NHÂN (INDIVIDUAL REPORT)
## Day 10 — Data Pipeline & Data Observability for RAG

- **Họ và tên:** Hoàng Quốc Việt
- **Mã sinh viên:** 2A202602563
- **Email:** viet.hq@vinuni.edu.vn
- **Vai trò trong nhóm:** AI & MLOps Specialist (Retrieval, Observability & Evaluation)
- **Tên nhóm / Lớp:** DataObservability_Team3 / K4-L3-DAY10
- **Tên Repository Nộp Bài:** `K4A-DAY10-Team3-DataPipeline`
- **Link GitHub Repository:** `https://github.com/[Tài-khoản-leader]/K4A-DAY10-Team3-DataPipeline`

---

## 1. TỔNG QUAN PHÂN CÔNG & VAI TRÒ CÁ NHÂN

Là AI & MLOps Specialist của nhóm, tôi phụ trách 3 mảng trọng tâm theo đúng tài liệu `1.docx`:
1. **Data Observability Gate:** Triển khai chốt kiểm định chất lượng tự động bằng **Great Expectations 1.x** (Ephemeral mode) và Freshness SLA.
2. **Vector Indexing & Retrieval:** Quản lý mô hình nhúng `all-MiniLM-L6-v2` và ChromaDB persistent collection.
3. **Evaluation & Reporting:** Xây dựng bộ đề thi Benchmark 5-10 câu phủ 5 dạng bài toán, tính điểm Hit Rate / Token F1, và xuất báo cáo đối chiếu 3 trạng thái.

---

## 2. CHI TIẾT CÁC CÔNG VIỆC VÀ MÃ NGUỒN ĐÃ THỰC HIỆN

### 2.1. Data Observability Gate với Great Expectations 1.x (`src/observability/quality.py`)
- Sử dụng chuẩn cú pháp mới **GX 1.x** dạng Ephemeral Mode (`gx.get_context(mode="ephemeral")`), tạo Data Source & Batch Definition qua `add_pandas()` và `add_dataframe_asset()`.
- Định nghĩa 4 Expectations thiết yếu:
  - `ExpectTableRowCountToBeBetween`: Số dòng từ 5 đến 5000.
  - `ExpectColumnValuesToNotBeNull`: Các cột `paper_id`, `title`, `text_for_embedding` không rỗng.
  - `ExpectColumnValuesToBeUnique`: Khoá `paper_id` độc nhất.
  - `ExpectColumnValueLengthsToBeBetween`: Độ dài `summary` >= 30 ký tự.
- Lập trình `build_freshness_report()`: Cảnh báo dữ liệu bị mốc (`is_fresh = False`) nếu tỉ lệ bài có `age_days > 180` vượt quá 25%.

### 2.2. Embedding & ChromaDB Vector Store (`src/retrieval/index.py` & `embeddings.py`)
- Tích hợp mô hình `sentence-transformers/all-MiniLM-L6-v2`.
- Quản lý và lưu trữ 3 collection riêng biệt trong ChromaDB (`papers-baseline`, `papers-corrupted`, `papers-repaired`) để cô lập không gian vector khi đánh giá đối chiếu.
- Xây dựng smoke test truy vấn vector (`LocalEmbeddingIndex.semantic_search`) trích xuất tài liệu từ ChromaDB.

### 2.3. Benchmark Test Set & Evaluation Metrics (`src/evaluation/testset.py` & `metrics.py`)
- Lập trình `load_or_create_test_set()` sinh bộ đề thi phủ 5 dạng câu hỏi: `summary`, `authors`, `date`, `category`, `multi_hop` (câu hỏi kết hợp liên ngành giữa hai chủ đề).
- Mỗi mẫu gồm các trường: `id`, `type`, `question`, `ground_truth`, `ground_truth_doc_ids`.
- Lập trình hàm tính chỉ số đánh giá `Hit Rate` (tỷ lệ tìm đúng tài liệu gốc) và `Token F1` (độ tương đồng câu trả lời của AI).

### 2.4. Báo Cáo Định Lượng Markdown (`src/observability/reporting.py`)
- Xây dựng module tự động xuất báo cáo Phase 1 (`data/reports/phase1_report.md`).
- Xây dựng module xuất báo cáo đối chiếu 3 trạng thái (`data/reports/corruption_report.md`) hiển thị bảng so sánh 3 cột: **Baseline vs Corrupted vs Repaired**.

---

## 3. KẾT QUẢ ĐẠT ĐƯỢC & BẰNG CHỨNG THỰC THI (EVIDENCE)

- Lệnh test Quality Gate: `python -c "from core.config import load_settings; from observability.quality import run_data_quality_checks; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); res=run_data_quality_checks(df, s, 'test'); print(f'Tín hiệu hoàn thành: Quality check status = {res[\"success\"]}')"` -> In ra `Tín hiệu hoàn thành: Quality check status = True`.
- Lệnh test Testset: `python -c "from core.config import load_settings; from evaluation.testset import load_or_create_test_set; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); ts=load_or_create_test_set(df, s.paths.test_set_json); print(f'Tín hiệu hoàn thành: Test set gồm {len(ts.samples)} câu hỏi')"` -> In ra `Tín hiệu hoàn thành: Test set gồm 5 câu hỏi`.
- Lệnh test Vector Retrieval: `python -c "from core.config import load_settings; from retrieval.index import LocalEmbeddingIndex; s=load_settings(); idx=LocalEmbeddingIndex(s, collection_name='papers-baseline'); idx.build_from_clean(); res=idx.semantic_search('machine learning', top_k=2); print(f'Tín hiệu hoàn thành: Tìm thấy {len(res)} tài liệu liên quan')"` -> In ra `Tín hiệu hoàn thành: Tìm thấy 2 tài liệu liên quan`.

---

## 4. BÀI HỌC VÀ KIẾN THỨC RÚT RA

1. **Ứng dụng Great Expectations 1.x:** Nắm chắc cú pháp mới của GX 1.x (Ephemeral mode) để xây dựng trạm kiểm soát dữ liệu tự động mà không đẻ file rác.
2. **Freshness SLA:** Hiểu tầm quan trọng của việc giám sát độ tươi dữ liệu để tránh cung cấp "kiến thức mốc meo" cho RAG Agent.
3. **Đánh giá RAG định lượng:** Làm chủ phương pháp đo lường Hit Rate & Token F1 để đánh giá khách quan năng lực của hệ thống AI.

---

## 5. CAM KẾT LIÊM CHÍNH HỌC THUẬT

Tôi xin cam đoan các đóng góp mã nguồn và báo cáo trên là hoàn toàn trung thực, do tôi tự tay lập trình với sự phối hợp cùng nhóm. Tôi đã hoàn tất nộp link repository GitHub lên VLearn LMS.
