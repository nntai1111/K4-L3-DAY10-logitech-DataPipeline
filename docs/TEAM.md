# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `logitech`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-logitech-DataPipeline` — https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline
- **Trưởng nhóm:** Nguyễn Như Tài (`nntai1111`)

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
  - Đóng góp chính: `corruption.py`, `phase1.py`, `corruption_flow.py` và bộ test ghép các module của nhóm thành hai lệnh chạy được. Ở lượt chạy nộp, sáu kịch bản lỗi (seed 42) đưa dữ liệu từ 24 xuống 22 dòng, 19 bài; pipeline không báo lỗi nào nhưng hit rate còn 0.800 và token F1 còn 0.745. Repair từ raw cho fingerprint trùng baseline (`a9364c4a…`) ở cả hai lần chạy, và cả 4 metric về lại baseline.
  - Điều tôi học được: một kịch bản lỗi chỉ có giá trị khi nó đi vào dữ liệu đến nơi và biết trước tín hiệu nào phải bắt nó. Vì vậy sau khi làm bẩn tôi dựng lại `text_for_embedding` và cộng `age_days` cho bài bị lùi ngày, còn mỗi sự kiện trong log ghi sẵn `detected_by`. Thứ tự các bước cũng quan trọng: drop trước duplicate nên số dòng chỉ giảm 2 và `row_count` không thấy gì, phải có check đối soát với nguồn.
  - Hỗ trợ ngoài phạm vi: gộp commit `demo` của Tài vào bản tích hợp (`99affeb`) để main chỉ còn một bộ code và artifact; sửa nhỏ `src/retrieval/` (nạp model từ cache, manifest dùng đường dẫn tương đối).

### ## NguyenNhuTai-2A202602976
- **Vai trò:** Data Ingestion & Cleaning owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/ingestion/crossref.py`: parse payload Crossref (loại JATS/HTML, chuẩn hoá DOI, tác giả, ngày), gọi API có retry/backoff cho 429/5xx, fallback snapshot offline, lưu raw response nguyên byte + `data/raw/ingestion_manifest.json` (SHA-256, mode).
  - `src/ingestion/cleaning.py`: chuẩn hoá schema, lọc bản ghi không hợp lệ, khử trùng lặp theo `paper_id`, tính `age_days`, sinh `text_for_embedding` 5 dòng; `dataset_fingerprint` dùng cho kiểm chứng repair.
  - Repair: dựng lại dữ liệu sạch từ `data/raw/crossref_records.json` bằng đúng quy tắc cleaning của baseline.
- **Điều học được / Đóng góp chính:**
  - Đóng góp chính: phần nạp và làm sạch dữ liệu mà mọi bước sau dùng chung, gồm 24 record trong `data/raw/crossref_records.json` (manifest `mode: snapshot`, SHA-256 raw `d968be68…`) và bảng sạch `data/clean/papers_clean.*` 24 dòng, 16 cột. Repair dựng lại từ raw qua cùng `build_clean_dataframe`; ở lần chạy nộp, fingerprint của hai lần repair trùng baseline (`a9364c4a…`) và file repaired giống từng byte file baseline.
  - Điều tôi học được quan trọng nhất: ở tầng cleaning, điền giá trị mặc định cho trường bắt buộc là tự tạo ra silent failure. Bản tôi tự làm (commit `d0474ec`) gán `published = 2026-01-01` hoặc `age_days = 0` cho bản ghi có ngày thiếu hay sai, nên bản ghi lỗi trông như bài mới nhất và regex ngày của gate vẫn cho qua. Bản trên main bỏ bản ghi đó và đếm lại. Snapshot 24 bài quá sạch để lộ lỗi này; chỉ test với payload bẩn mới thấy.
  - Trưởng nhóm: tạo repo nộp bài (fork về tài khoản `nntai1111`) và mời các thành viên. Tôi viết bản đầu của `crossref.py` và `cleaning.py` (cùng cả pipeline) trong `d0474ec`; khi tích hợp, commit `b918ef7` của Long ghi đè bản này bằng bản tích hợp (merge `99affeb`).

### ## HoangQuocViet-2A202602563
- **Vai trò:** Evaluation & Observability owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/evaluation/testset.py`: bộ test cố định 10 câu / 4 loại (`summary`, `authors`, `date`, `categories`), câu hỏi khớp logic trích câu trả lời của `retrieval/qa.py`; tái sử dụng cùng bộ test cho cả 3 trạng thái.
  - `src/observability/quality.py`: quality gate Great Expectations 1.x (ephemeral context, 4 loại expectation bắt buộc gồm 6 expectation + 6 check mở rộng, tổng 12) và Freshness SLA (`age_days > 180`, cảnh báo khi > 25%).
  - `src/observability/reporting.py`: `phase1_report.md` và `corruption_report.md` (bảng 3 trạng thái, phân tích nguyên nhân → hệ quả tự động từ artifact).
- **Điều học được / Đóng góp chính:**
  - Đóng góp chính: ba module trên cho ra test set cố định `data/eval/test_set.json`, các báo cáo quality/freshness trong `data/quality/` và hai báo cáo Markdown trong `data/reports/`. Ở lần chạy nộp, gate pass 12/12 với baseline và repaired, còn với dữ liệu hỏng thì fail 7/12 và freshness chuyển STALE (31.8%), bắt đủ 6/6 kịch bản lỗi. Check `source_papers_present` (đối soát `paper_id` với raw snapshot) là check duy nhất trong gate GX bắt được lỗi mất bài mới nhất.
  - Điều tôi học được quan trọng nhất là silent failure: pipeline chạy không báo lỗi, metric câu trả lời vẫn có thể xanh trong khi dữ liệu đã sai. Ở trạng thái corrupted, `eval_001` lấy câu trả lời từ sai bài nguồn mà judge vẫn chấm 5/5; chỉ retrieval hit (đo bằng `ground_truth_doc_ids`) và gate mới lộ ra. Vì vậy gate phải chạy trước khi dữ liệu vào vector store.
  - Hỗ trợ ngoài phạm vi: tự làm một bản pipeline đầy đủ thứ hai (nhánh `feat/viet-pipeline`) để nhóm so sánh khi chọn phần ghép vào main, và một app demo Streamlit trên bản đó (agent trên ChromaDB, tab silent failure, tab observability, nạp bài Crossref mới chỉ sau khi qua gate). Hai phần này không nằm trong code nộp.
