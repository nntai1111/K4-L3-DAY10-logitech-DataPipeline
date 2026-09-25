# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `logitech`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10` (Khóa K4)
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-logitech-DataPipeline` (https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline)

---

## # Thành viên

| STT | Họ và tên | MSSV | GitHub | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Như Tài | 2A202602976 | `nntai1111` | Trưởng nhóm, chủ repo. Đã làm: fork repo lớp, tạo repo nhóm, mời collaborator. Được giao: review và merge PR vào `main`, tái hiện hai script từ clean clone trên máy riêng, kiểm tra Insights > Contributors trước khi nộp. | `report/2A202602976_NguyenNhuTai.md` |
| 2 | Lò Văn Long | 2A202602541 | `getlmt` | Kiểm chứng độc lập và phân tích. Được giao: chạy lại hai script trên máy thứ hai, chạy `run_corruption_flow.py` hai lần để xác nhận sha256 bảng repaired không đổi, review quality gate và phân tích corruption. | `report/2A202602541_LoVanLong.md` |
| 3 | Hoàng Quốc Việt | 2A202602563 | `Catnip-harvest` | Implementation & integration owner: `crossref.py`, `cleaning.py`, `quality.py`, `testset.py`, `corruption.py`, `reporting.py`, `phase1.py`, `corruption_flow.py`, `common.py`; sửa `retrieval/index.py`; giao diện `app/` (B1), auto-repair (B2), bộ pytest `tests/` (B3). | `report/2A202602563_HoangQuocViet.md` |

*(Nhóm 3 thành viên. Toàn bộ code pipeline do một thành viên viết, nên hai thành viên còn lại nhận phần kiểm chứng: tái hiện trên máy khác, review và nghiệm thu trước khi nộp.)*

---

## # Cá nhân

### ## NguyenNhuTai-2A202602976
- **Vai trò:** Trưởng nhóm, chủ repo, phụ trách tái hiện và nghiệm thu bài nộp.
- **Công việc chi tiết đã hoàn thành:**
  - Fork repo lớp `VinUni-AI20k/K4-L3A-Day10-Data-Pipeline-Data-Observability` về tài khoản `nntai1111`, đặt tên `K4-L3-DAY10-logitech-DataPipeline`.
  - Thiết lập repo nhóm và mời các thành viên làm collaborator.
- **Công việc được giao, chờ xác nhận:**
  - Review và merge PR chứa pipeline vào `main`. Trạng thái: `[CẦN TÀI XÁC NHẬN]`
  - Clone sạch nhánh `main` trên máy riêng, chạy `python script/run_phase1.py` và `python script/run_corruption_flow.py`, ghi kết quả vào bảng "Kết quả tái hiện" của `report/group_report.md`. Trạng thái: `[CẦN TÀI XÁC NHẬN]`
  - Kiểm tra tab Insights > Contributors của nhánh `main`, xác nhận cả ba thành viên đều xuất hiện trước khi nộp. Trạng thái: `[CẦN TÀI XÁC NHẬN]`
- **Điều học được / Đóng góp chính:**
  - `[TÀI TỰ VIẾT]`

### ## LoVanLong-2A202602541
- **Vai trò:** Kiểm chứng độc lập trên máy thứ hai và phân tích kết quả.
- **Công việc được giao, chờ xác nhận:**
  - Chạy `python script/run_phase1.py` và `python script/run_corruption_flow.py` trên máy thứ hai, so các chỉ số với `data/results/*_metrics.json` của bài nộp. Trạng thái: `[CẦN LONG XÁC NHẬN]`
  - Trên máy thứ hai, chạy `python script/run_corruption_flow.py` lần thứ hai, xác nhận `data/results/repair_idempotency.json` ghi `matches_previous_run: true` (sha256 bảng repaired trùng lần chạy trước). Trạng thái: `[CẦN LONG XÁC NHẬN]`
  - Review quality gate (`src/observability/quality.py`) và phân tích sáu kịch bản corruption, viết phần hỏi đáp và phân tích trong báo cáo cá nhân bằng lời của mình. Trạng thái: `[CẦN LONG XÁC NHẬN]`
- **Điều học được / Đóng góp chính:**
  - `[LONG TỰ VIẾT]`

### ## HoangQuocViet-2A202602563
- **Vai trò:** Implementation & integration owner, viết toàn bộ phần code pipeline và các hạng mục bonus.
- **Công việc chi tiết đã hoàn thành:**
  - `src/ingestion/crossref.py`: parse response Crossref thành `PaperRecord` (bỏ thẻ JATS, chuẩn hóa DOI, chọn ngày theo thứ tự ưu tiên, bỏ item thiếu DOI/title/abstract/ngày); gọi API live khi `REFRESH_SOURCE=1` với retry 3 lần cho mã 429/500/502/503/504, tôn trọng header `Retry-After`; mọi lỗi live đều quay về snapshot `data/raw/crossref_response.json`, và snapshot chỉ bị ghi đè khi lần gọi live thành công; `load_raw_records` đọc lại records cho bước repair.
  - `src/ingestion/cleaning.py`: `build_clean_dataframe` nhận `run_date` cố định thay vì đọc đồng hồ, tính `age_days`, khử trùng lặp theo `paper_id`, sinh `text_for_embedding` 5 phần; `refresh_derived_columns` dùng lại sau corruption.
  - `src/observability/quality.py`: quality gate Great Expectations 1.x (`gx.get_context(mode="ephemeral")`, `data_sources.add_pandas`, batch definition), 4 expectation bắt buộc theo Guide cộng 2 expectation bổ sung (độ dài `title`, chuỗi ký hiệu rác trong `summary`); freshness SLA (quá 25% dòng có `age_days > 180` là stale), ghi `gate_passed` = GX và freshness.
  - `src/evaluation/testset.py`: bộ 10 câu hỏi cố định (3 summary, 3 authors, 2 date, 2 categories) rải đều theo ngày xuất bản, câu chữ khớp cách `retrieval/qa.py` định tuyến câu hỏi, ground truth đúng dạng chuỗi mà index lưu.
  - `src/ingestion/corruption.py`: 6 kịch bản với seed 42; bốn kịch bản sửa trường sau bước bỏ bài nhắm vào các nhóm dòng không trùng nhau; bỏ 4 bài và nhân bản 4 dòng giữ số dòng ở 24; ghi `data/results/corruption_log.json`.
  - `src/observability/reporting.py`: `generate_phase1_report` và `generate_corruption_report` (bảng 3 trạng thái, bảng expectation, kịch bản nào bị check nào bắt, từng câu hỏi, phần idempotent repair).
  - `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py`, `src/pipelines/common.py`: hai entrypoint; GX fail thì dừng không index baseline; `run_context.json` lưu `run_date` và sha256 bảng baseline; repair tự kích hoạt khi gate fail, dựng lại từ raw với cùng `run_date`, ghi bằng chứng sha256 vào `data/results/repair_idempotency.json`.
  - `src/core/config.py`: thêm `RUN_DATE` và đường dẫn `run_context`. `src/retrieval/index.py`: manifest embedding lưu `persist_path` tương đối thay vì đường dẫn tuyệt đối của máy chạy.
  - Bonus B1: `app/` (Streamlit) gồm ba tab: trợ lý nghiên cứu hỏi trên một collection, tab "Silent failure" đặt cùng một câu hỏi lên ba collection baseline/corrupted/repaired và hiện câu trả lời cạnh nhau, và trang quan sát dữ liệu đọc artifact. Bonus B2: auto-repair khi gate fail. Bonus B3: bộ pytest trong `tests/` (252 test, coverage `src/` 99%), chạy một lệnh bằng `bash script/run_tests.sh`, có workflow GitHub Actions chạy trên Python 3.11.
- **Điều học được / Đóng góp chính:**
  - Một lỗi dữ liệu có thể giữ nguyên số dòng và qua mặt kiểm tra row count: trong bài, bỏ 4 bài mới nhất rồi nhân bản 4 dòng khiến bảng vẫn 24 dòng, và `drop_latest_records` không bị expectation nào bắt.
  - Repair chỉ idempotent khi mọi đầu vào của bước làm sạch đều cố định, kể cả ngày chạy. Cố định `run_date` là điều kiện để sha256 bảng repaired trùng bảng baseline.
