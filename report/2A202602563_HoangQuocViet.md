# Member Role Report — Day 10: Data Pipeline & Data Observability

> Bản nháp: phần kỹ thuật đã điền từ code và artifact thực tế. Các mục `[Tự viết]` do chính thành viên hoàn thành bằng lời của mình. Nhớ xoá dòng ghi chú này trước khi nộp.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Hoàng Quốc Việt |
| MSSV | 2A202602563 |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | `logitech` |
| GitHub | `Catnip-harvest` |
| Email | vietmocno.1@gmail.com |
| Vai trò chính | Evaluation & Observability owner |
| Repository | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Evaluation set | `src/evaluation/testset.py` — `build_test_set`, `load_or_build_test_set` | Clean dataframe | `data/eval/test_set.json` (10 câu, 4 loại) | Hoàn thành |
| Quality gate & freshness | `src/observability/quality.py` — `run_data_quality_checks`, `compute_freshness`, `build_freshness_report` | Dataframe của từng trạng thái | `data/quality/*_quality_report.json`, `*_freshness_report.json`, `data/quality/gx/*.json` | Hoàn thành |
| Reporting | `src/observability/reporting.py` — `generate_phase1_report`, `generate_corruption_report`, `summarize_answers`, `format_comparison_table` | Metrics, quality, freshness, corruption log, answers | `data/reports/phase1_report.md`, `data/reports/corruption_report.md`, bảng so sánh trên console | Hoàn thành |

Liên hệ với thành viên khác: dùng clean schema của Tài; gate, test set và report được Long ghép vào `phase1.py` và `corruption_flow.py`.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| `[Tự viết]` | `[Tự viết]` | `[Tự viết]` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Test set cố định khớp logic trả lời của `qa.py` | `build_test_set` | 10 câu: summary 3, authors 3, date 2, categories 2 | Tín hiệu CP2: `Sinh được 10 câu hỏi test`; `tests/test_testset.py` |
| Quality gate GX 1.x | `run_data_quality_checks` | Baseline 12/12 pass; corrupted 7/12 (5 check fail đúng loại lỗi); repaired 12/12 | Tín hiệu CP1: `Quality check status = True` |
| Freshness SLA | `compute_freshness`, `build_freshness_report` | Baseline 4.2% stale (FRESH); corrupted 31.8% (STALE) | `data/quality/freshness_report.json`, `corrupted_freshness_report.json` |
| Báo cáo 3 trạng thái + phân tích nguyên nhân tự động | `generate_corruption_report` | Bảng đối chiếu, gate theo từng check, tác động từng câu, nguyên nhân → hệ quả | `data/reports/corruption_report.md` |

Output cụ thể: `data/quality/corrupted_quality_report.json` cho thấy gate bắt đúng 5 loại lỗi: `paper_id_unique` (6 dòng), `summary_min_length` (3), `title_min_length` (4), `summary_no_noise` (3) và `source_papers_present` (thiếu 5 paper). Loại lỗi thứ 6 (stale date) do freshness SLA phát hiện.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần này cần một cách đo chất lượng RAG ổn định giữa các trạng thái (benchmark cố định), và một lớp observability phát hiện dữ liệu xấu **trước** khi dữ liệu vào vector store. Dữ liệu xấu có thể không làm metric RAG thay đổi nhưng vẫn gây hại.

### Cách triển khai

**Test set:**
- Chọn 10 paper trải đều theo ngày xuất bản và xoay vòng 4 loại câu hỏi.
- Mẫu câu hỏi đặt tiêu đề trong dấu nháy đơn và dùng cụm "who authored", "when was", "what categories", để `qa.py` chọn đúng trường trả lời.
- Bỏ các title chứa dấu nháy.
- Tái sử dụng file cũ, trừ khi `REFRESH_TEST_SET=1` hoặc file tham chiếu tới paper đã mất.

**Gate:**
- `gx.get_context(mode="ephemeral")` → `add_pandas` → `add_dataframe_asset` → `add_batch_definition_whole_dataframe` → `get_batch`, rồi một `ExpectationSuite` gồm 12 expectation.
- 4 loại bắt buộc: row count 5–5000; not null cho `paper_id`, `title`, `text_for_embedding`; unique `paper_id`; summary ≥ 30 ký tự.
- 8 check mở rộng, mỗi check nhắm một loại lỗi: schema, title ≥ 8, regex ký hiệu rác, regex DOI, ngày ISO, và đối soát `paper_id` với raw snapshot.
- Kết quả GX gốc được lưu vào `data/quality/gx/`.

**Freshness:** dòng có `age_days > 180` tính là stale; `is_fresh = False` khi tỉ lệ stale vượt 25%. Nếu không có tuổi hợp lệ nào thì trả về `UNKNOWN`.

**Report:** đọc trực tiếp từ artifact, không nhập số tay; phần phân tích nguyên nhân được sinh bằng cách đối chiếu corruption log với kết quả từng câu hỏi.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Clean dataframe 16 cột (cần `paper_id`, `title`, `summary`, `published`, `age_days`, `text_for_embedding`, `authors_joined`, `categories_joined`) |
| Output | `test_set.json` (`id`, `question_type`, `question`, `ground_truth`, `ground_truth_doc_ids`); báo cáo quality có khoá `success`; báo cáo freshness có `is_fresh`, `stale_ratio`; 2 báo cáo Markdown |
| Module phụ thuộc | `ingestion.cleaning` (hằng số ngưỡng, rebuild nguồn để đối soát), `ingestion.crossref` (đọc raw), `retrieval.qa` (quy ước câu hỏi) |
| Module sử dụng output | `evaluation.metrics` (test set), `pipelines.phase1` và `pipelines.corruption_flow` (gate, freshness, report) |
| Điều kiện lỗi cần xử lý | Thiếu cột → `ValueError`; ít hơn 4 tài liệu dùng được → `ValueError`; không có raw snapshot → bỏ check đối soát nguồn; thiếu cột `age_days` → freshness `UNKNOWN` |

### Cách xác minh

```bash
python -c "from core.config import load_settings; from observability.quality import run_data_quality_checks; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); res=run_data_quality_checks(df, s, 'test'); print(f'Tín hiệu hoàn thành: Quality check status = {res[\"success\"]}')"
python -c "from core.config import load_settings; from evaluation.testset import build_test_set; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); ts=build_test_set(df, s.paths.eval_testset); print(f'Tín hiệu hoàn thành: Sinh được {len(ts)} câu hỏi test')"
python -m pytest tests/test_quality.py tests/test_testset.py tests/test_reporting.py -q
```

- **Kết quả mong đợi:** `Quality check status = True`, `Sinh được 10 câu hỏi test`, test pass.
- **Kết quả thực tế:** đúng như mong đợi (đã chạy 2026-09-25); bộ test sinh lại giống hệt từng byte với file đang dùng.
- **Artifact/log:** `data/quality/baseline_quality_report.json`, `data/eval/test_set.json`, `data/reports/corruption_report.md`.

## 5. Một quyết định kỹ thuật quan trọng

`[Tự viết]` (gợi ý chủ đề có thật trong phần việc: thêm check đối soát nguồn `source_papers_present` để bắt lỗi drop records; tách freshness thành cảnh báo thay vì làm gate fail; giữ test set cố định cho 3 trạng thái; dùng meta `check_id` để map kết quả GX)

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

**Họ và tên:** Hoàng Quốc Việt
**Ngày xác nhận:** `[YYYY-MM-DD]`
