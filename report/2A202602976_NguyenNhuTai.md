# Member Role Report — Day 10: Data Pipeline & Data Observability

> Bản nháp: phần kỹ thuật đã điền từ code và artifact thực tế. Các mục `[Tự viết]` do chính thành viên hoàn thành bằng lời của mình. Nhớ xoá dòng ghi chú này trước khi nộp.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Như Tài |
| MSSV | 2A202602976 |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | `logitech` |
| GitHub | `nntai1111` |
| Email | taibeo161023@gmail.com |
| Vai trò chính | Data Ingestion & Cleaning owner |
| Repository | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Raw ingestion | `src/ingestion/crossref.py` — `parse_crossref_payload`, `fetch_source_records`, `load_raw_records` | Crossref `/works` (live) hoặc snapshot `data/raw/crossref_response.json` | `data/raw/crossref_records.json`, `data/raw/ingestion_manifest.json` | Hoàn thành |
| Cleaning & data modeling | `src/ingestion/cleaning.py` — `build_clean_dataframe`, `refresh_derived_columns`, `save_clean_dataframe`, `dataset_fingerprint` | `list[PaperRecord]`, run date | `data/clean/papers_clean.csv`, `.json` (24 dòng, 16 cột) | Hoàn thành |
| Nguồn cho repair | Quy tắc cleaning dùng lại trong `repair_from_raw` | `data/raw/crossref_records.json` | Dataset repaired có fingerprint trùng baseline | Hoàn thành |

Liên hệ với thành viên khác: clean schema là contract cho quality gate và test set (Việt) và cho index, corruption, repair (Long).

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| `[Tự viết]` | `[Tự viết]` | `[Tự viết]` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Parse payload Crossref (bỏ JATS/HTML, chuẩn hoá DOI, tác giả, ngày) | `parse_crossref_payload` | Tái tạo chính xác 24 record của `crossref_records.json` | `tests/test_crossref.py::test_parser_reproduces_committed_records` |
| Gọi API có retry/backoff, fallback snapshot | `fetch_source_records`, `_request_crossref` | Lỗi 429/503/mạng → dùng snapshot, không crash | `tests/test_crossref.py` (retry, fallback, không có snapshot) |
| Lưu lineage raw | `data/raw/ingestion_manifest.json` | Mode, số item hợp lệ, SHA-256 raw response | Tín hiệu CP0: `Đã tải 24 bài báo` |
| Làm sạch và mô hình hoá | `build_clean_dataframe` | 24 dòng, `age_days`, `text_for_embedding` 5 dòng | Tín hiệu CP1: `Clean thành công 24 dòng` |
| Fingerprint dữ liệu | `dataset_fingerprint` | So khớp baseline với repaired (`a9364c4a…`) | `data/results/repair_log.json` |

Output cụ thể: `data/raw/ingestion_manifest.json` ghi `mode=snapshot`, 24/24 item hợp lệ và SHA-256 `d968be68…` của raw response, giúp truy vết dữ liệu sạch về đúng bản raw đã dùng.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần này đưa dữ liệu bài báo từ Crossref vào pipeline một cách tin cậy: không mất bản gốc (raw preservation), chạy được khi mất mạng hoặc API quá tải, và tạo ra một bảng sạch có schema ổn định để các module sau dùng chung.

### Cách triển khai

**Parse:**
- `title` và `abstract` được bỏ thẻ JATS, bao gồm heading `<jats:title>Abstract</jats:title>` và thẻ inline như `<sub>`, rồi decode HTML entity và chuẩn hoá khoảng trắng.
- DOI được hạ về chữ thường và bỏ tiền tố `https://doi.org/`.
- Ngày lấy theo thứ tự ưu tiên `published → published-online → published-print → issued → created`, hỗ trợ `date-parts` thiếu tháng hoặc ngày.
- Record thiếu DOI, title, abstract hoặc ngày bị bỏ.

**Fetch:**
- Mặc định đọc snapshot. Khi `REFRESH_SOURCE=1`, pipeline gọi API tối đa 4 lần, chờ theo `Retry-After` hoặc 2s·2^(n−1).
- Nếu thất bại thì fallback về snapshot.
- Khi gọi live thành công, raw response được lưu nguyên byte, bản snapshot cũ được lưu vào `data/raw/archive/`.
- `crossref_records.json` chỉ được ghi lại khi nội dung thay đổi, để không tạo diff giả.

**Clean:**
- Bỏ bản ghi có title dưới 8 ký tự, summary dưới 30 ký tự, hoặc ngày không parse được theo ISO 8601.
- Dedupe theo `paper_id`, giữ bản `updated` mới nhất.
- Tính `age_days = (run_date − published).days`.
- Sinh `text_for_embedding` gồm 5 dòng.
- Sắp xếp mới nhất trước. Thống kê làm sạch được lưu trong `df.attrs["cleaning_stats"]`.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Payload Crossref `message.items[]` (DOI, title, abstract, author, subject, published, created, URL) |
| Output | `list[PaperRecord]` (11 trường) → clean dataframe 16 cột; CSV lưu list dưới dạng JSON string, JSON giữ nguyên mảng |
| Module phụ thuộc | `core.config` (đường dẫn, query, filter), `core.utils` |
| Module sử dụng output | `observability.quality`, `evaluation.testset`, `retrieval.index`, `ingestion.corruption`, `pipelines.corruption_flow` (repair) |
| Điều kiện lỗi cần xử lý | HTTP 429/5xx, timeout, mất mạng → fallback snapshot; không có snapshot và API lỗi → `RuntimeError` rõ nghĩa; payload rỗng hoặc sai cấu trúc → không ghi đè snapshot; record thiếu trường bắt buộc → bị loại và được đếm |

### Cách xác minh

```bash
python -c "from core.config import load_settings; from ingestion.crossref import fetch_source_records; s=load_settings(); r=fetch_source_records(s); print(f'Tín hiệu hoàn thành: Đã tải {len(r)} bài báo')"
python -c "from datetime import datetime, timezone; from core.config import load_settings; from ingestion.crossref import load_raw_records; from ingestion.cleaning import build_clean_dataframe; s=load_settings(); df=build_clean_dataframe(load_raw_records(s.paths.raw_records_json), datetime.now(timezone.utc)); print(f'Tín hiệu hoàn thành: Clean thành công {len(df)} dòng')"
python -m pytest tests/test_crossref.py tests/test_cleaning.py -q
```

- **Kết quả mong đợi:** `Đã tải 24 bài báo`, `Clean thành công 24 dòng`, test pass.
- **Kết quả thực tế:** đúng như mong đợi (đã chạy 2026-09-25).
- **Artifact/log:** `data/raw/ingestion_manifest.json`, `data/clean/papers_clean.csv`.

## 5. Một quyết định kỹ thuật quan trọng

`[Tự viết]` (gợi ý chủ đề có thật trong phần việc: mặc định đọc snapshot thay vì gọi API; lưu raw response nguyên byte và lưu snapshot cũ trước khi ghi đè; chỉ ghi lại records khi nội dung đổi; dùng DOI chữ thường làm document ID)

- **Bối cảnh:** `[Tự viết]`
- **Các phương án đã cân nhắc:** `[Tự viết]`
- **Phương án đã chọn:** `[Tự viết]`
- **Lý do:** `[Tự viết]`
- **Bằng chứng quyết định phù hợp:** `[Tự viết]`

## 6. Một lỗi hoặc blocker đã xử lý

`[Tự viết]`

- **Triệu chứng/lỗi nguyên văn:** `[Tự viết]`
- **Lệnh hoặc bước tái hiện:** `[Tự viết]`
- **Nguyên nhân gốc:** `[Tự viết]`
- **Cách xử lý:** `[Tự viết]`
- **Cách xác minh sau khi sửa:** `[Tự viết]`
- **Điều học được:** `[Tự viết]`

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

`[Tự viết — trả lời 5 câu hỏi trong mẫu bằng lời của mình]`

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | --: | --: | --: | --- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | `[Tự viết]` |
| `mean_token_f1` | 1.000 | 0.745 | 1.000 | `[Tự viết]` |
| `judge_accuracy` | 1.000 | 0.800 | 1.000 | `[Tự viết]` |
| `mean_judge_score` | 5.000 | 4.200 | 5.000 | `[Tự viết]` |
| Quality checks | 12/12 pass | 7/12 pass | 12/12 pass | `[Tự viết]` |
| Freshness status | FRESH (4.2%) | STALE (31.8%) | FRESH (4.2%) | `[Tự viết]` |

### Kết luận từ số liệu

`[Tự viết — hai chuỗi nguyên nhân → tín hiệu → metric; tham khảo data/reports/corruption_report.md §6]`

## 9. Điều học được và hướng cải thiện

`[Tự viết]`

## 10. Cam kết của thành viên

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [ ] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Như Tài
**Ngày xác nhận:** `[YYYY-MM-DD]`
