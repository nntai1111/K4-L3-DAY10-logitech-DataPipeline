# Member Role Report — Day 10: Data Pipeline & Data Observability

> Ghi chú cho Tài (xóa trước khi nộp): các dữ kiện chung của nhóm (repo, kiến trúc pipeline, số liệu trong artifact, nhiệm vụ được giao) đã được điền sẵn. Ô `[TÀI TỰ VIẾT]` là phần Tài tự viết bằng lời của mình. Ô `[CẦN TÀI XÁC NHẬN]` chỉ được thay bằng kết quả sau khi Tài đã tự chạy hoặc tự kiểm tra; nếu chưa làm được thì ghi rõ trạng thái thật.

## 1. Thông tin cá nhân

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Họ và tên       | Nguyễn Như Tài |
| MSSV               | 2A202602976 |
| Khóa/Lớp         | K4 |
| Tên nhóm         | logitech |
| Vai trò chính    | Trưởng nhóm, chủ repo, tái hiện và nghiệm thu bài nộp |
| Repository         | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | `[TÀI TỰ VIẾT]` |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao  | Trạng thái                                 |
| ------------------ | --------------------- | ---------------- | ----------------- | -------------------------------------------- |
| Repo nhóm | Fork `VinUni-AI20k/K4-L3A-Day10-Data-Pipeline-Data-Observability`, repo `nntai1111/K4-L3-DAY10-logitech-DataPipeline`, Settings > Collaborators | Repo starter của lớp | Repo nhóm có đủ collaborator | Hoàn thành |
| Review và merge | PR chứa pipeline vào nhánh `main` | PR của Hoàng Quốc Việt | Code pipeline trên `main` | `[CẦN TÀI XÁC NHẬN]` |
| Tái hiện từ clean clone | `script/run_phase1.py`, `script/run_corruption_flow.py` | Clone mới của `main` trên máy Tài | Hai dòng của Tài trong bảng "Kết quả tái hiện" (`report/group_report.md`, mục 4) | `[CẦN TÀI XÁC NHẬN]` |
| Kiểm tra Contributors | GitHub Insights > Contributors, nhánh `main` | Lịch sử commit của repo | Xác nhận cả ba thành viên xuất hiện trước khi nộp | `[CẦN TÀI XÁC NHẬN]` |

Phần việc tái hiện phụ thuộc vào code của Hoàng Quốc Việt (toàn bộ `src/ingestion/`, `src/observability/`, `src/evaluation/testset.py`, `src/pipelines/`, `app/`). Kết quả tái hiện của Tài là bằng chứng bài nộp chạy được trên máy khác máy tác giả, bổ sung cho kiểm chứng trên máy thứ hai của Lò Văn Long.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                         | Thành viên/module được hỗ trợ | Kết quả                    |
| ------------------------------------ | ------------------------------------ | ---------------------------- |
| `[TÀI TỰ VIẾT]` | `[TÀI TỰ VIẾT]` | `[TÀI TỰ VIẾT]` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao       | Cách xác minh         |
| --------------------------- | ----------------------------- | ------------------------- | ----------------------- |
| Fork repo lớp, tạo repo nhóm, mời collaborator | GitHub Settings > Collaborators | Repo `nntai1111/K4-L3-DAY10-logitech-DataPipeline` | Trang repo trên GitHub |
| Review và merge PR vào `main` | `[CẦN TÀI XÁC NHẬN]` (số PR) | `[CẦN TÀI XÁC NHẬN]` | Lịch sử PR trên GitHub |
| Chạy baseline từ clean clone | `script/run_phase1.py` | `[CẦN TÀI XÁC NHẬN]` | Exit code và `data/results/baseline_metrics.json` trên máy Tài |
| Chạy corruption flow từ clean clone | `script/run_corruption_flow.py` | `[CẦN TÀI XÁC NHẬN]` | Exit code, `data/results/repair_idempotency.json` trên máy Tài |
| Kiểm tra Insights > Contributors | Nhánh `main` | `[CẦN TÀI XÁC NHẬN]` | Ảnh chụp hoặc mô tả trang Contributors |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`[TÀI TỰ VIẾT]`

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Bài nộp phải chạy được end-to-end trên máy giám khảo, không chỉ trên máy người viết code (rubric trừ 15 điểm nếu không chạy được, trừ 5 điểm nếu có đường dẫn tuyệt đối). Tái hiện từ clean clone trên máy thứ hai là cách kiểm tra điều đó trước khi nộp. Merge vào `main` và kiểm tra Contributors quyết định việc chấm điểm từng thành viên, vì GitHub chỉ ghi nhận đóng góp trên nhánh mặc định.

### Cách triển khai

`[TÀI TỰ VIẾT]`

### Input, output và contract

| Thành phần                   | Mô tả                                     |
| ------------------------------ | ------------------------------------------- |
| Input                          | Clone mới của nhánh `main`; `.env` tạo từ `.env.example` (không commit) |
| Output                         | Kết quả hai script trên máy Tài, ghi vào bảng "Kết quả tái hiện" của `report/group_report.md` |
| Module phụ thuộc             | `script/run_phase1.py`, `script/run_corruption_flow.py`, `pyproject.toml`, `uv.lock` |
| Module sử dụng output        | `report/group_report.md` (mục 4 và checklist mục 13) |
| Điều kiện lỗi cần xử lý | `[TÀI TỰ VIẾT]` |

### Cách xác minh

```bash
git clone https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline.git
cd K4-L3-DAY10-logitech-DataPipeline
uv sync
cp .env.example .env   # đặt RUN_DATE=2026-09-25; LLM_PROVIDER=gemini, LLM_MODEL=gemini-3.5-flash-lite và GOOGLE_API_KEY để judge so được, hoặc LLM_PROVIDER=mock nếu không có key (khi đó chỉ so hit rate và token F1)
source .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
python script/run_phase1.py
python script/run_corruption_flow.py
```

- **Kết quả mong đợi:** Cả hai lệnh kết thúc với exit code 0. Với cùng snapshot và `RUN_DATE=2026-09-25`, hit rate và token F1 của baseline, corrupted, repaired lần lượt là 1.000, 0.800, 1.000 như trong `data/results/*_metrics.json` của bài nộp, và `repair_idempotency.json` ghi `repaired_matches_baseline: true`.
- **Kết quả thực tế:** `[CẦN TÀI XÁC NHẬN]`
- **Artifact/log:** `[CẦN TÀI XÁC NHẬN]`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** `[TÀI TỰ VIẾT]`
- **Các phương án đã cân nhắc:** `[TÀI TỰ VIẾT]`
- **Phương án đã chọn:** `[TÀI TỰ VIẾT]`
- **Lý do:** `[TÀI TỰ VIẾT]`
- **Bằng chứng quyết định phù hợp:** `[TÀI TỰ VIẾT]`

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `[TÀI TỰ VIẾT]`
- **Lệnh hoặc bước tái hiện:** `[TÀI TỰ VIẾT]`
- **Nguyên nhân gốc:** `[TÀI TỰ VIẾT]`
- **Cách xử lý:** `[TÀI TỰ VIẾT]`
- **Cách xác minh sau khi sửa:** `[TÀI TỰ VIẾT]`
- **Điều học được:** `[TÀI TỰ VIẾT]`

Nếu chưa xử lý xong:

- **Phạm vi bị ảnh hưởng:** `[TÀI TỰ VIẾT]`
- **Những gì đã loại trừ:** `[TÀI TỰ VIẾT]`
- **Bước tiếp theo:** `[TÀI TỰ VIẾT]`

## 7. Hiểu biết về luồng end-to-end

Luồng của nhóm để đối chiếu (chi tiết ở `report/group_report.md`, mục 3):

```text
data/raw/crossref_response.json (snapshot Crossref, 24 bài)
  -> crossref_records.json -> papers_clean (24 dòng, run_date 2026-09-25)
  -> quality gate GX 1.x + freshness SLA -> ChromaDB papers-baseline (MiniLM, top_k 4)
  -> 10 câu hỏi cố định -> baseline_metrics.json
  -> 6 kịch bản corruption (seed 42) -> papers-corrupted -> corrupted_metrics.json
  -> repair từ crossref_records.json, cùng run_date -> papers-repaired -> repaired_metrics.json
  -> corruption_report.md
```

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

`[TÀI TỰ VIẾT]`

## 8. Phân tích kết quả

### Metrics chính

Số liệu lấy từ artifact của lần chạy chính thức (`data/results/*_metrics.json`, `data/quality/*.json`), LLM judge `gemini` / `gemini-3.5-flash-lite`, cả 30 verdict do LLM chấm.

| Metric/signal          | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| ---------------------- | -------: | --------: | -------: | ------------------------- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | `[TÀI TỰ VIẾT]` |
| `mean_token_f1`      | 1.000 | 0.800 | 1.000 | `[TÀI TỰ VIẾT]` |
| `judge_accuracy`     | 1.000 | 0.800 | 1.000 | `[TÀI TỰ VIẾT]` |
| `mean_judge_score`   | 5.000 | 4.200 | 5.000 | `[TÀI TỰ VIẾT]` |
| Quality checks         | 8/8 PASS | 4/8 PASS | 8/8 PASS | `[TÀI TỰ VIẾT]` |
| Freshness status       | Fresh, 1/24 dòng quá hạn | Stale, 13/24 | Fresh, 1/24 | `[TÀI TỰ VIẾT]` |

### Kết luận từ số liệu

1. `[TÀI TỰ VIẾT]`
2. `[TÀI TỰ VIẾT]`

Corruption nào ảnh hưởng rõ nhất và vì sao?

`[TÀI TỰ VIẾT]`

Kết quả nào khác với kỳ vọng ban đầu?

`[TÀI TỰ VIẾT]`

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. `[TÀI TỰ VIẾT]`
2. `[TÀI TỰ VIẾT]`
3. `[TÀI TỰ VIẾT]`

### Nếu có thêm thời gian

`[TÀI TỰ VIẾT]`

## 10. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [ ] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Như Tài
**Ngày xác nhận:** `[TÀI TỰ VIẾT]`
