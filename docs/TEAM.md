# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `logitech`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-logitech-DataPipeline` — https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline

---

## # Thành viên

| STT | Họ và tên | MSSV | GitHub | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|---|
| 1 | Lò Văn Long | 2A202602541 | [`getlmt`](https://github.com/getlmt) | longlo.261295@gmail.com | Corruption & Integration owner (`src/ingestion/corruption.py`, `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py`, `src/pipelines/common.py`, `tests/`) | `report/2A202602541_LoVanLong.md` |
| 2 | Nguyễn Như Tài | 2A202602976 | [`nntai1111`](https://github.com/nntai1111) | taibeo161023@gmail.com | Data Ingestion & Cleaning owner (`src/ingestion/crossref.py`, `src/ingestion/cleaning.py`, raw data trong `data/raw/`) | `report/2A202602976_NguyenNhuTai.md` |
| 3 | Hoàng Quốc Việt | 2A202602563 | [`Catnip-harvest`](https://github.com/Catnip-harvest) | vietmocno.1@gmail.com | Evaluation & Observability owner (`src/evaluation/testset.py`, `src/observability/quality.py`, `src/observability/reporting.py`) | `report/2A202602563_HoangQuocViet.md` |

Phân công theo mẫu nhóm 3 thành viên trong `report/README.md` (mục 5).

### Phân công theo checkpoint

| Checkpoint | Nội dung | Owner chính | Hỗ trợ |
|---|---|---|---|
| CP0 | Môi trường (`uv sync`), `.env`, raw ingestion + fallback offline | Tài (`crossref.py`) | Long (thiết lập môi trường) |
| CP1 | Cleaning, `age_days`, `text_for_embedding`; quality gate GX 1.x + freshness SLA | Tài (`cleaning.py`), Việt (`quality.py`) | — |
| CP2 | Test set 10 câu / 4 loại; ChromaDB `papers-baseline` | Việt (`testset.py`) | Long (index trong pipeline) |
| CP3 | Baseline end-to-end + `phase1_report.md` | Long (`phase1.py`) | Việt (`reporting.py`) |
| CP4 | 6 kịch bản corruption + đo suy giảm | Long (`corruption.py`, `corruption_flow.py`) | Việt (check phát hiện lỗi) |
| CP5 | Idempotent repair + báo cáo 3 trạng thái | Long (`corruption_flow.py`) | Tài (repair từ raw), Việt (`corruption_report.md`) |
| CP6 | Live demo, Q&A, nộp bài | Cả nhóm | — |

---

## # Cá nhân

### ## LoVanLong-2A202602541
- **Vai trò:** Corruption & Integration owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/ingestion/corruption.py`: 6 kịch bản làm bẩn dữ liệu có seed cố định (drop latest 20%, blank summary, inject noise, truncate title < 8 ký tự, stale date −365 ngày, duplicate rows), ghi log trước/sau vào `data/results/corruption_log.json`.
  - `src/pipelines/phase1.py`: điều phối baseline; quality gate chạy **trước** khi index (gate fail thì dừng, không index dữ liệu xấu); demo agent tool-calling.
  - `src/pipelines/corruption_flow.py`: corruption → phát hiện → đo silent failure → auto-repair từ raw khi gate fail → đối chiếu 3 trạng thái; chứng minh idempotent bằng fingerprint.
  - `tests/` + `script/run_tests.py`: 83 test pytest, coverage 97%, chạy offline với `LLM_PROVIDER=mock`.
- **Điều học được / Đóng góp chính:**
  - `[Tự viết]`

### ## NguyenNhuTai-2A202602976
- **Vai trò:** Data Ingestion & Cleaning owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/ingestion/crossref.py`: parse payload Crossref (loại JATS/HTML, chuẩn hoá DOI, tác giả, ngày), gọi API có retry/backoff cho 429/5xx, fallback snapshot offline, lưu raw response nguyên byte + `data/raw/ingestion_manifest.json` (SHA-256, mode).
  - `src/ingestion/cleaning.py`: chuẩn hoá schema, lọc bản ghi không hợp lệ, khử trùng lặp theo `paper_id`, tính `age_days`, sinh `text_for_embedding` 5 dòng; `dataset_fingerprint` dùng cho kiểm chứng repair.
  - Repair: dựng lại dữ liệu sạch từ `data/raw/crossref_records.json` bằng đúng quy tắc cleaning của baseline.
- **Điều học được / Đóng góp chính:**
  - `[Tự viết]`

### ## HoangQuocViet-2A202602563
- **Vai trò:** Evaluation & Observability owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/evaluation/testset.py`: bộ test cố định 10 câu / 4 loại (`summary`, `authors`, `date`, `categories`), câu hỏi khớp logic trích câu trả lời của `retrieval/qa.py`; tái sử dụng cùng bộ test cho cả 3 trạng thái.
  - `src/observability/quality.py`: quality gate Great Expectations 1.x (ephemeral context, 4 expectation bắt buộc + 8 check mở rộng) và Freshness SLA (`age_days > 180`, cảnh báo khi > 25%).
  - `src/observability/reporting.py`: `phase1_report.md` và `corruption_report.md` (bảng 3 trạng thái, phân tích nguyên nhân → hệ quả tự động từ artifact).
- **Điều học được / Đóng góp chính:**
  - `[Tự viết]`
