# BÁO CÁO ĐÓNG GÓP CÁ NHÂN (INDIVIDUAL REPORT)
## Day 10 — Data Pipeline & Data Observability for RAG

- **Họ và tên:** Nguyễn Như Tài
- **Mã sinh viên:** 2A202602976
- **Email:** tai.nn@vinuni.edu.vn
- **Vai trò trong nhóm:** Trưởng nhóm (Team Lead) & Pipeline Lead Infrastructure Architect
- **Tên nhóm / Lớp:** DataObservability_Team3 / K4-L3-DAY10
- **Tên Repository Nộp Bài:** `K4A-DAY10-Team3-DataPipeline`
- **Link GitHub Repository:** `https://github.com/[Tài-khoản-của-bạn]/K4A-DAY10-Team3-DataPipeline`

---

## 1. TỔNG QUAN PHÂN CÔNG & VAI TRÒ CÁ NHÂN

Là Trưởng nhóm và Pipeline Lead, tôi chịu trách nhiệm thiết lập hạ tầng cốt lõi, điều phối kiến trúc luồng dữ liệu, quản lý module `core/`, xây dựng 2 pipeline thực thi chính (`phase1.py` & `corruption_flow.py`), quản lý repository GitHub (`K4A-DAY10-Team3-DataPipeline`), code review và đảm bảo bài làm tuân thủ đầy đủ checklist nộp bài theo đúng tài liệu thực hành `1.docx`.

---

## 2. CHI TIẾT CÁC CÔNG VIỆC VÀ MÃ NGUỒN ĐÃ THỰC HIỆN

### 2.1. Cấu Hình Hạ Tầng & Môi Trường (`src/core/`)
- Fork starter repo về tài khoản cá nhân, đổi tên repo thành `K4A-DAY10-Team3-DataPipeline` và add các thành viên **Lò Văn Long**, **Hoàng Quốc Việt** vào Collaborators.
- Thiết lập môi trường ảo Python 3.11+, cài đặt dependencies qua `python -m pip install -e .` (editable package mode) để đảm bảo `src/` được nhận diện như package nội bộ.
- Khởi tạo file `.env` từ `.env.example` và cấu hình biến môi trường (`GOOGLE_API_KEY`, provider `gemini`).
- Hoàn thiện module `src/core/config.py`, `src/core/paths.py`, `src/core/models.py`.

### 2.2. Điều Phối Baseline Pipeline (`src/pipelines/phase1.py` & `script/run_phase1.py`)
- Lập trình hàm điều phối `run_phase1_pipeline()` liên kết các mắt xích:
  1. Gọi `fetch_source_records` lấy dữ liệu thô từ Crossref API (hoặc fallback snapshot local `data/raw/crossref_response.json`).
  2. Gọi `build_clean_dataframe` làm sạch, chuẩn hóa text và tính `age_days`.
  3. Chạy Quality Gate `run_data_quality_checks` (GX 1.x Ephemeral mode) & Freshness Check.
  4. Nạp vector vào ChromaDB collection `papers-baseline`.
  5. Sinh Benchmark test set (`load_or_create_test_set`) gồm 5 dạng câu hỏi (`summary`, `authors`, `date`, `category`, `multi_hop`).
  6. Đánh giá chỉ số Hit Rate/Token F1/LLM Judge Score ban đầu.
- Xây dựng entrypoint `script/run_phase1.py`.

### 2.3. Điều Phối Corruption & Idempotent Repair Pipeline (`src/pipelines/corruption_flow.py` & `script/run_corruption_flow.py`)
- Kết nối kịch bản tiêm lỗi dữ liệu (`corruption.py`) với không gian vector `papers-corrupted`.
- Thực thi cơ chế khôi phục dữ liệu sạch từ bản lưu trữ thô `data/raw/crossref_records.json` (Idempotent Repair).
- Đánh giá lại RAG trên dữ liệu đã phục hồi (`papers-repaired`) và kích hoạt module xuất báo cáo đối chiếu 3 trạng thái `data/reports/corruption_report.md`.
- Xây dựng entrypoint `script/run_corruption_flow.py`.

### 2.4. Phân Công & Quản Lý Repo GitHub
- Cập nhật thông tin phân công chi tiết tại `docs/TEAM.md` và `HUONG_DAN_HOAN_THIEN_PROJECT.md`.
- Kiểm tra tính hợp lệ của Git commit history trên nhánh `main` (Insights > Contributors).

---

## 3. KẾT QUẢ ĐẠT ĐƯỢC & BẰNG CHỨNG THỰC THI (EVIDENCE)

1. Lệnh kiểm tra môi trường: `python -c "import chromadb, great_expectations, sentence_transformers; print('Môi trường sẵn sàng')"` -> In ra `Môi trường sẵn sàng`.
2. Lệnh `python script/run_phase1.py` chạy thành công end-to-end, sinh đầy đủ 5 artifacts:
   - `data/clean/papers_clean.csv`
   - `data/chroma/`
   - `data/eval/test_set.json`
   - `data/results/baseline_metrics.json`
   - `data/reports/phase1_report.md`
3. Lệnh `python script/run_corruption_flow.py` chạy thành công, chứng minh:
   - AI sụt giảm chỉ số nghiêm trọng khi gặp dữ liệu bẩn (Silent Failure).
   - AI lấy lại 100% phong độ ban đầu sau khi kích hoạt Idempotent Repair.
   - Báo cáo `data/reports/corruption_report.md` xuất ra bảng so sánh 3 cột rõ ràng.

---

## 4. BÀI HỌC VÀ KIẾN THỨC RÚT RA

1. **Hiểm họa Silent Failure:** Hiểu rõ tại sao RAG Agent không báo lỗi đắng lòng mà tự tin trả lời sai khi data pipeline bị hỏng.
2. **Kiến trúc Idempotent System:** Nắm vững nguyên lý bảo toàn dữ liệu gốc (Raw Preservation) giúp pipeline có khả năng tự phục hồi mà không phụ thuộc vào thao tác thủ công.
3. **Kỹ năng điều phối nhóm:** Học cách phân chia công việc hợp lý theo năng lực thành viên (Data Eng vs AI/MLOps), quản lý mốc thời gian 240 phút hiệu quả.

---

## 5. CAM KẾT LIÊM CHÍNH HỌC THUẬT

Tôi xin cam đoan các thông tin đóng góp trên là đúng thực tế, toàn bộ mã nguồn do tôi và nhóm trực tiếp thực hiện. Tôi đã hoàn thành việc nộp đường link repository GitHub lên VLearn LMS bằng tài khoản cá nhân của mình.
