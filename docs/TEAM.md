# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `DataObservability_Team3`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4A-DAY10-Team3-DataPipeline`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Như Tài | 2A202602976 | tai.nn@vinuni.edu.vn | Trưởng nhóm / Pipeline Lead (`core/`, `phase1.py`, `corruption_flow.py`, `script/`) | `report/2A202602976_NguyenNhuTai.md` |
| 2 | Lò Văn Long | 2A202602541 | long.lv@vinuni.edu.vn | Data Engineer (`crossref.py`, `cleaning.py`, `corruption.py`, Raw Data & Repair) | `report/2A202602541_LoVanLong.md` |
| 3 | Hoàng Quốc Việt | 2A202602563 | viet.hq@vinuni.edu.vn | AI & MLOps Specialist (`retrieval/`, `quality.py` GX 1.x, `testset.py`, reporting) | `report/2A202602563_HoangQuocViet.md` |

---

## # Cá nhân

### ## NguyenNhuTai-2A202602976
- **Vai trò:** Trưởng nhóm & Điều phối Pipeline Infrastructure.
- **Công việc chi tiết đã hoàn thành:**
  - Thiết lập môi trường ảo `.venv`, cấu hình hệ thống `core/config.py` và đường dẫn artifacts `core/paths.py`.
  - Kết nối luồng thực thi trong `src/pipelines/phase1.py` và `src/pipelines/corruption_flow.py`.
  - Xây dựng entrypoint scripts: `script/run_phase1.py` và `script/run_corruption_flow.py`.
  - Kiểm tra tính nhất quán của các artifacts và theo dõi Contributor tracking trên GitHub nhánh `main`.
- **Điều học được / Đóng góp chính:**
  - Hiểu sâu sắc về thiết kế Idempotent Pipeline và quản lý trạng thái luồng dữ liệu đa tầng.

### ## LoVanLong-2A202602541
- **Vai trò:** Phụ trách Ingestion, Làm sạch & Phục hồi dữ liệu.
- **Công việc chi tiết đã hoàn thành:**
  - Xây dựng module thu thập Crossref API với cơ chế Dual-Mode Fallback offline trong `src/ingestion/crossref.py`.
  - Chuẩn hóa schema, tính toán trường `age_days` và `text_for_embedding` trong `src/ingestion/cleaning.py`.
  - Xây dựng 6 kịch bản tiêm lỗi dữ liệu trong `src/ingestion/corruption.py`.
  - Thực thi cơ chế Idempotent Repair phục hồi dữ liệu từ raw snapshot.
- **Điều học được / Đóng góp chính:**
  - Kỹ thuật truy vết nguồn gốc dữ liệu (Data Lineage) và bảo toàn raw snapshot trước khi biến đổi.

### ## HoangQuocViet-2A202602563
- **Vai trò:** Phụ trách RAG Vector Index, Data Observability & Evaluation.
- **Công việc chi tiết đã hoàn thành:**
  - Quản lý mô hình embedding `sentence-transformers/all-MiniLM-L6-v2` và nạp ChromaDB (`papers-baseline`, `papers-corrupted`, `papers-repaired`).
  - Thiết lập Quality Gate theo chuẩn mới **Great Expectations 1.x** (ephemeral mode) và giám sát Freshness SLA trong `src/observability/quality.py`.
  - Xây dựng bộ câu hỏi đánh giá chuẩn 5 dạng (`summary`, `authors`, `date`, `category`, `multi_hop`) trong `src/evaluation/testset.py`.
  - Đo lường và xuất bảng đối chiếu 3 trạng thái vào `data/reports/corruption_report.md` thông qua `src/observability/reporting.py`.
- **Điều học được / Đóng góp chính:**
  - Cách thiết lập hệ thống cảnh báo sớm chặn đứng hiện tượng Silent Failure trước khi dữ liệu vào serving layer.
