# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Khóa/Lớp         | K4                         |
| Tên nhóm         | logitech                   |
| Repository         | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | 2026-09-25                 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Nguyễn Như Tài | 2A202602976 | Trưởng nhóm, chủ repo, tái hiện và nghiệm thu | Đã làm: fork repo lớp, tạo repo nhóm, mời collaborator. Được giao: review và merge PR vào `main` `[CẦN TÀI XÁC NHẬN]`, tái hiện hai script từ clean clone `[CẦN TÀI XÁC NHẬN]`, kiểm tra Insights > Contributors `[CẦN TÀI XÁC NHẬN]` |
| 2 | Lò Văn Long | 2A202602541 | Kiểm chứng độc lập và phân tích | Được giao: chạy lại hai script trên máy thứ hai và chạy corruption flow hai lần để đối chiếu sha256 `[CẦN LONG XÁC NHẬN]`; review quality gate và phân tích corruption `[CẦN LONG XÁC NHẬN]` |
| 3 | Hoàng Quốc Việt | 2A202602563 | Implementation & integration owner | `src/ingestion/crossref.py`, `cleaning.py`, `corruption.py`; `src/observability/quality.py`, `reporting.py`; `src/evaluation/testset.py`; `src/pipelines/phase1.py`, `corruption_flow.py`, `common.py`; sửa `src/retrieval/index.py` và `src/core/config.py`; `app/` (B1), auto-repair (B2), `tests/` (B3) |

## 2. Tóm tắt kết quả

**Tóm tắt của nhóm:**

Nhóm đã hoàn thành cả hai flow bắt buộc. `script/run_phase1.py` đọc snapshot Crossref 24 bài (chế độ `snapshot`), làm sạch còn 24 dòng, kiểm định bằng Great Expectations 1.x (8/8 expectation đạt, freshness 1/24 dòng quá 180 ngày), index vào ChromaDB collection `papers-baseline` và chấm 10 câu hỏi cố định: hit rate 1.000, token F1 1.000. Artifact gồm raw response và raw records, bảng sạch CSV/JSON, manifest embedding, test set, báo cáo quality và freshness, metrics, `run_context.json` và `phase1_report.md`.

`script/run_corruption_flow.py` tiêm 6 kịch bản lỗi với seed 42. Trên dữ liệu bẩn, hit rate và token F1 cùng giảm từ 1.000 xuống 0.800, trong khi bảng vẫn có 24 dòng nên kiểm tra row count vẫn PASS. Quality gate bắt được 5 trên 6 kịch bản: 4 qua GX, 1 qua freshness SLA (13/24 dòng quá hạn). `drop_latest_records` là kịch bản duy nhất không expectation nào bắt, và cũng là kịch bản hại agent nhiều nhất: 2 câu hỏi mất tài liệu đúng khỏi top-4.

Repair dựng lại bảng từ `data/raw/crossref_records.json` với cùng `run_date` và phục hồi mọi chỉ số về mức baseline. sha256 bảng repaired trùng sha256 bảng baseline và trùng lần repair trước (corruption flow đã chạy hai lần). Lần chạy chính thức dùng LLM judge `gemini` / `gemini-3.5-flash-lite`, và cả 30 verdict (10 mỗi trạng thái) đều do LLM chấm. Giới hạn lớn nhất còn lại: gate không có check nào cho việc mất bài mới nhất, và cả token F1 lẫn LLM judge đều chấm đạt một câu trả lời đúng nhưng lấy từ nhầm bài (eval_010).

### Hạng mục bonus

| Hạng mục | Nội dung | Bằng chứng |
| --- | --- | --- |
| B1 Dashboard | Streamlit, ba tab: trợ lý nghiên cứu hỏi trên một collection chọn ở sidebar (agent có tool, tự chuyển về chế độ trích xuất `retrieval/qa.py` khi không có LLM); "Silent failure" đặt cùng một câu hỏi (chọn từ 10 câu của test set hoặc tự nhập) lên ba collection baseline/corrupted/repaired và hiện câu trả lời cạnh nhau, bằng truy xuất và trích xuất, không gọi LLM; trang quan sát dữ liệu (3 trạng thái, bảng quality gate, thanh freshness, biểu đồ phân bố `age_days` có vạch 180 ngày, 6 kịch bản, từng câu hỏi, sha256 repair). Trang chỉ đọc artifact và index đã build, không tự chạy pipeline. | `app/streamlit_app.py`, `app/research.py`, `app/data.py` |
| B2 Auto-repair | Khi `gate_passed` của batch bẩn là `false`, repair tự kích hoạt từ raw records và ghi `auto_triggered: true`. Bảng repaired phải qua GX, nếu không flow dừng bằng `SystemExit`. Trong bài lab, repair cũng chạy cả khi gate pass để luôn có cột Repaired so sánh. | `src/pipelines/corruption_flow.py`, `data/results/repair_idempotency.json` |
| B3 Pytest | Bộ test trong `tests/` chạy trên thư mục tạm, không ghi vào `data/` thật, provider LLM ép về `mock`, `run_date` cố định. Kết quả `bash script/run_tests.sh` ngày 2026-09-25: 249 test pass trong 54.97 giây, coverage `src/` 99% (1063 câu lệnh, thiếu 6). Test end-to-end chạy `phase1` một lần và `corruption_flow` hai lần trong project tạm. Workflow `.github/workflows/tests.yml` chạy bộ test trên Python 3.11 | `tests/`, `script/run_tests.sh` |

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
script/run_phase1.py
  data/raw/crossref_response.json          (snapshot; REFRESH_SOURCE=1 thì gọi Crossref live, lỗi thì quay về snapshot)
    -> parse_crossref_payload              -> data/raw/crossref_records.json
    -> build_clean_dataframe(run_date)     -> data/clean/papers_clean.csv, papers_clean.json
    -> run_data_quality_checks             -> data/quality/baseline_quality_report.json, freshness_report.json
         (GX fail thì dừng, không index)
    -> LocalEmbeddingIndex.build           -> ChromaDB papers-baseline, data/embeddings/papers_embeddings.json
    -> load_or_create_test_set             -> data/eval/test_set.json
    -> evaluate_pipeline                   -> data/results/baseline_metrics.json, baseline_answers.json
    -> run_context.json                    (run_date, baseline_sha256, test_set_sha256)
    -> generate_phase1_report              -> data/reports/phase1_report.md

script/run_corruption_flow.py
  data/clean/papers_clean.json + run_context.json
    -> corrupt_clean_dataframe(seed 42)    -> data/clean/papers_clean_corrupted.*, data/results/corruption_log.json
    -> quality gate (ghi nhận, không chặn) -> data/quality/corrupted_quality_report.json
    -> index papers-corrupted + evaluate   -> data/results/corrupted_metrics.json
    -> gate fail => repair từ raw records, cùng run_date -> data/clean/papers_clean_repaired.*
    -> quality gate (bắt buộc PASS)        -> data/quality/repaired_quality_report.json
    -> index papers-repaired + evaluate    -> data/results/repaired_metrics.json
    -> so sha256 với baseline              -> data/results/repair_idempotency.json
    -> generate_corruption_report          -> data/reports/corruption_report.md
```

Ở bước corrupted, pipeline vẫn index batch bẩn dù gate fail (observe mode) để đo xem lỗi sẽ gây hại gì nếu lọt vào serving layer. Trong vận hành thật, gate fail sẽ dừng batch tại đó, như `phase1.py` đang làm với baseline.

### Trách nhiệm của từng khối

| Khối             | Input          | Xử lý chính             | Output/artifact          | Owner          |
| ----------------- | -------------- | -------------------------- | ------------------------ | -------------- |
| Ingestion         | Crossref `/works` hoặc `data/raw/crossref_response.json` | Fetch live có retry 3 lần, fallback snapshot, parse, bỏ thẻ JATS, chuẩn hóa DOI | `data/raw/crossref_response.json`, `data/raw/crossref_records.json` | Hoàng Quốc Việt |
| Cleaning          | `list[PaperRecord]`, `run_date` | Chuẩn hóa text, parse ngày, `age_days`, dedupe `paper_id`, `text_for_embedding` | `data/clean/papers_clean.csv`, `.json` | Hoàng Quốc Việt |
| Embedding/index   | Bảng sạch | MiniLM `all-MiniLM-L6-v2`, ChromaDB cosine, 3 collection tách biệt | `data/chroma/`, `data/embeddings/*.json` | Code starter của lớp; Hoàng Quốc Việt sửa `persist_path` tương đối |
| Evaluation        | Bảng sạch, index | 10 câu hỏi cố định, hit rate, token F1, LLM judge (`metrics.py` của starter) | `data/eval/test_set.json`, `data/results/*_metrics.json` | Hoàng Quốc Việt (`testset.py`) |
| Observability     | Bảng sạch/bẩn/repaired | GX 1.x 8 expectation, freshness SLA 180 ngày / 25% | `data/quality/*.json` | Hoàng Quốc Việt; review: Lò Văn Long `[CẦN LONG XÁC NHẬN]` |
| Corruption/repair | Bảng baseline, raw records | 6 kịch bản seed 42; repair dựng lại từ raw, cùng `run_date` | `corruption_log.json`, `papers_clean_corrupted.*`, `papers_clean_repaired.*`, `repair_idempotency.json` | Hoàng Quốc Việt |
| Orchestration     | `.env`, artifact pha 1 | Thứ tự chạy, gate, `run_context.json`, báo cáo | `phase1_report.md`, `corruption_report.md` | Hoàng Quốc Việt; tái hiện: Nguyễn Như Tài `[CẦN TÀI XÁC NHẬN]`, Lò Văn Long `[CẦN LONG XÁC NHẬN]` |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình             | Giá trị sử dụng |
| ---------------------------- | ------------------- |
| `LLM_PROVIDER`             | `gemini` (theo `data/results/run_context.json`) |
| `LLM_MODEL`                | `gemini-3.5-flash-lite` (LLM judge và agent demo) |
| Embedding model              | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 (`max_results = 24`) |
| Retrieval`top_k`           | 4 |
| Freshness threshold          | `age_days > 180` là quá hạn; stale khi quá 25% số dòng quá hạn |
| Random seed, nếu có        | 42 (corruption) |
| `run_date`                  | 2026-09-25 (lấy ngày UTC khi chạy pha 1, hoặc đặt bằng `RUN_DATE=YYYY-MM-DD`; corruption flow đọc lại từ `run_context.json`) |

Không dán nội dung API key hoặc file `.env` vào báo cáo.

### Lệnh cài đặt

```bash
uv sync
# Chỉ cần cho giao diện Streamlit (bonus B1):
uv pip install -r app/requirements.txt
```

Kích hoạt môi trường trước khi chạy: `source .venv/Scripts/activate` (Git Bash trên Windows), `.venv\Scripts\Activate.ps1` (PowerShell) hoặc `source .venv/bin/activate` (macOS/Linux). Tạo `.env` từ `.env.example`, đặt `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash-lite` và `GOOGLE_API_KEY` để tái hiện đúng lần chạy chính thức. Máy không có API key có thể đặt `LLM_PROVIDER=mock` để chạy hết pipeline, nhưng khi đó chỉ so được hit rate và token F1.

### Lệnh chạy

Baseline:

```bash
python script/run_phase1.py
```

Corruption flow:

```bash
python script/run_corruption_flow.py
```

Giao diện và bộ test:

```bash
streamlit run app/streamlit_app.py
bash script/run_tests.sh
```

### Kết quả tái hiện

| Lệnh             | Trạng thái                                    | Thời điểm chạy gần nhất | Bằng chứng                         |
| ----------------- | ----------------------------------------------- | ----------------------------- | ------------------------------------ |
| Baseline pipeline, lần chạy chính thức (máy Việt, Windows 11, `gemini` / `gemini-3.5-flash-lite`) | Thành công | 2026-09-25 08:39 UTC | `data/results/run_context.json`, `data/reports/phase1_report.md` |
| Corruption flow, lần chạy chính thức, chạy hai lần (máy Việt) | Thành công; lần hai ghi `matches_previous_run: true` | 2026-09-25 08:42 UTC | `data/results/repair_idempotency.json`, `data/reports/corruption_report.md` |
| Baseline pipeline, clean clone `main` (máy Tài) | `[CẦN TÀI XÁC NHẬN]` | `[CẦN TÀI XÁC NHẬN]` | `[CẦN TÀI XÁC NHẬN]` |
| Corruption flow, clean clone `main` (máy Tài) | `[CẦN TÀI XÁC NHẬN]` | `[CẦN TÀI XÁC NHẬN]` | `[CẦN TÀI XÁC NHẬN]` |
| Hai script trên máy thứ hai, corruption flow chạy hai lần (máy Long) | `[CẦN LONG XÁC NHẬN]` | `[CẦN LONG XÁC NHẬN]` | `matches_previous_run` trong `repair_idempotency.json`: `[CẦN LONG XÁC NHẬN]` |

Mọi số liệu trong báo cáo này lấy từ lần chạy chính thức: toàn bộ thư mục `data/` được sinh lại từ đầu, và cả 30 verdict judge đều do LLM chấm (dòng "Verdict LLM / heuristic" trong `corruption_report.md` ghi 10 / 0 cho mỗi trạng thái).

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính                | Giá trị                             |
| --------------------------- | ------------------------------------- |
| Source                      | Crossref REST API `https://api.crossref.org/works`; bài nộp chạy chế độ `snapshot` từ `data/raw/crossref_response.json` |
| Query/filter                | `query=agentic retrieval augmented generation large language model`, `filter=from-pub-date:<hôm nay trừ 180 ngày>,has-abstract:true` (lần chạy 2026-09-25 ghi `from-pub-date:2026-03-29`), `rows=24`. Filter chỉ áp dụng ở chế độ live |
| Thời điểm lấy dữ liệu | Snapshot có sẵn trong repo starter (commit `ebae089`, 2026-09-24); pipeline đọc snapshot lúc 2026-09-25 08:39 UTC |
| Số record nhận được    | 24 item trong response, 24 record sau parse, 24 dòng sau làm sạch |
| Cơ chế retry/backoff      | Chỉ khi `REFRESH_SOURCE=1`: tối đa 3 lần, thử lại với mã 429/500/502/503/504, chờ theo header `Retry-After` hoặc 2^n giây, timeout 30 giây. Mọi lỗi live (HTTP, mạng, JSON hỏng) quay về snapshot; snapshot chỉ bị ghi đè khi lần gọi live thành công |

### Raw và clean schema

| Trường        | Kiểu dữ liệu | Bắt buộc?  | Ý nghĩa   | Xử lý khi thiếu/sai |
| --------------- | --------------- | ------------ | ----------- | ---------------------- |
| `paper_id` | `str` | Có | DOI chuẩn hóa, là document ID | Bỏ tiền tố `doi.org`/`doi:`, chữ thường; thiếu thì bỏ item |
| `title` | `str` | Có | Tiêu đề bài | Chuẩn hóa khoảng trắng; thiếu thì bỏ item |
| `summary` | `str` | Có | Abstract đã bỏ thẻ | Bỏ thẻ JATS/HTML, giải mã entity; thiếu thì bỏ item |
| `authors` | `list[str]` | Không | Tên tác giả | Ghép `given` + `family`, bỏ tên rỗng |
| `categories`, `primary_category` | `list[str]`, `str` | Không | Trường `subject` của Crossref; loại chính là phần tử đầu | Danh sách rỗng thì chuỗi rỗng |
| `published` | `str` ISO | Có | Ngày xuất bản | Lấy theo thứ tự `published`, `published-print`, `published-online`, `issued`, `created`; thiếu tháng/ngày thì lấy 01; không parse được thì bỏ dòng |
| `updated` | `str` ISO | Không | Ngày cập nhật | Lấy từ `updated`/`deposited`/`indexed`, không có thì bằng `published` |
| `abs_url`, `pdf_url`, `comment` | `str` | Không | Liên kết và ghi chú nguồn | `pdf_url` không có link PDF thì bằng `abs_url` |
| `authors_joined`, `categories_joined` | `str` | Không | Danh sách nối bằng `, ` | Chuỗi rỗng nếu danh sách rỗng |
| `summary_chars` | `int` | Có | Độ dài `summary` | Tính lại sau mọi thay đổi `summary` |
| `age_days` | `int` | Có | `run_date` trừ `published` | Tính từ `run_date` cố định, không từ đồng hồ |
| `text_for_embedding` | `str` | Có | Văn bản đưa vào embedding | Sinh lại sau cleaning và sau corruption |

### Quy tắc cleaning

| Quy tắc                                 | Quality dimension liên quan | Số record bị tác động | Cách xác minh      |
| ---------------------------------------- | ---------------------------- | -------------------------: | -------------------- |
| Bỏ thẻ JATS/HTML và giải mã entity trong abstract | Validity | 24 | Mọi abstract trong `crossref_response.json` bọc `<jats:p>`; `summary` trong `papers_clean.json` không còn ký tự `<`, `>` |
| Bỏ item thiếu DOI, title, abstract hoặc ngày | Completeness | 0 | 24 item vào, 24 record ra (`crossref_records.json`) |
| Khử trùng lặp theo `paper_id` (giữ bản đầu) | Uniqueness | 0 | 24 dòng, `expect_column_values_to_be_unique(paper_id)` PASS |
| `updated` bằng `published` khi nguồn không có ngày cập nhật | Completeness | 24 | Snapshot không có trường `updated`/`deposited`/`indexed` |
| `pdf_url` bằng `abs_url` khi không có link PDF | Completeness | 24 | Snapshot không có trường `link` |
| `age_days` tính từ `run_date` cố định | Timeliness | 24 | `run_date` 2026-09-25 trong `run_context.json`; sha256 bảng repaired trùng baseline |

Giải thích cách nhóm tạo `text_for_embedding`, document ID và `age_days`:

`text_for_embedding` gồm 5 dòng theo thứ tự `Title:`, `Authors:`, `Published:`, `Categories:`, `Summary:`, nên câu hỏi về tác giả, ngày hay lĩnh vực đều có token khớp trong văn bản được embed. Document ID là `paper_id` (DOI chữ thường, bỏ tiền tố). Trong ChromaDB mỗi vector có `record_id = <paper_id>::<vị trí dòng>`, nên dòng nhân bản vẫn được index thành vector riêng; đây chính là cách `duplicate_rows` chiếm chỗ trong top-k. `age_days = run_date - published` tính bằng ngày, với `run_date` truyền vào hàm thay vì đọc đồng hồ, để dựng lại từ cùng raw records luôn ra cùng một bảng.

## 6. Evaluation setup

| Thành phần                             | Cấu hình thực tế          |
| ---------------------------------------- | ----------------------------- |
| Số câu hỏi                            | 10 |
| Các`question_type`                    | `summary` (3), `authors` (3), `date` (2), `categories` (2) |
| Ground-truth document ID                 | `paper_id` của bài được hỏi. Bài được chọn từ bảng sạch (bỏ tiêu đề có dấu nháy đơn), sắp theo ngày, 10 vị trí rải đều từ bài cũ nhất đến mới nhất. Ground truth ở đúng dạng chuỗi index lưu: câu đầu của `summary`, `authors_joined`, `published`, `categories_joined` |
| Embedding model                          | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection                  | ChromaDB tại `data/chroma/`, cosine; `papers-baseline`, `papers-corrupted`, `papers-repaired` |
| Retrieval`top_k`                       | 4 |
| LLM provider/model                       | `gemini` / `gemini-3.5-flash-lite`; LLM judge chấm cả 30 câu (10 mỗi trạng thái), 0 verdict heuristic |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json`, sha256 `4f224de9590c82b77111ccd5265fd3645d20e1ab6ca10eca4985572b7e44c494` (`run_context.json`) |

Giải thích vì sao test set được giữ nguyên khi đánh giá baseline, corrupted và repaired:

Chỉ khi câu hỏi và ground truth không đổi thì chênh lệch chỉ số mới quy được về dữ liệu. `load_or_create_test_set` dùng lại file đã có miễn là mọi `ground_truth_doc_ids` còn trong corpus, và corruption flow đọc đúng file đó cho cả ba trạng thái. Nếu sinh test set từ bảng bẩn, câu hỏi sẽ được đặt trên tiêu đề đã bị cắt và ngày đã bị lùi, và bài bị bỏ sẽ không bao giờ được hỏi, nên chính lỗi cần đo sẽ biến mất khỏi phép đo. Câu chữ câu hỏi cũng được giữ khớp cách `retrieval/qa.py` định tuyến (`who authored`, `when was`, `what categories`, tiêu đề trong dấu nháy đơn để tra theo tiêu đề), để baseline không bị điểm thấp vì lý do không liên quan đến chất lượng dữ liệu.

## 7. Kết quả baseline

### Artifact checklist

| Artifact                 | Đường dẫn thực tế                | Trạng thái | Ghi chú   |
| ------------------------ | -------------------------------------- | ------------ | ---------- |
| Raw response/records     | `data/raw/crossref_response.json`, `data/raw/crossref_records.json` | Có | 24 item, 24 record |
| Cleaned dataset          | `data/clean/papers_clean.csv`, `papers_clean.json` | Có | 24 dòng, 16 cột |
| Embedding manifest/index | `data/embeddings/papers_embeddings.json`, `data/chroma/` | Có | Collection `papers-baseline`, 24 document, `persist_path` tương đối `data/chroma` |
| Evaluation set           | `data/eval/test_set.json` | Có | 10 câu |
| Baseline metrics         | `data/results/baseline_metrics.json` | Có | Kèm `baseline_answers.json` từng câu |
| Quality/freshness        | `data/quality/baseline_quality_report.json`, `freshness_report.json` | Có | GX 1.18.0, ephemeral context |
| Baseline report          | `data/reports/phase1_report.md` | Có | Sinh lúc 2026-09-25 08:39 UTC |
| Agent demo               | `data/results/agent_demo_answers.json` | Có | 2 câu hỏi mở do agent trong `retrieval/agent.py` trả lời bằng `gemini-3.5-flash-lite` |

### Baseline metrics

| Metric                 |       Giá trị | Diễn giải                             |
| ---------------------- | --------------: | --------------------------------------- |
| `retrieval_hit_rate` | 1.000 | Cả 10 câu đều có tài liệu đúng trong top-4; mọi câu đều tra đúng bài theo tiêu đề |
| `mean_token_f1`      | 1.000 | Câu trả lời trùng ground truth ở cả 4 loại câu hỏi |
| `judge_accuracy`     | 1.000 | LLM judge `gemini-3.5-flash-lite` chấm đúng cả 10/10 câu (10 verdict LLM, 0 heuristic) |
| `mean_judge_score`   | 5.000 | Cả 10 câu được chấm 5/5 |
| Ragas, nếu có        | N/A | Không chạy; `baseline_metrics.json` ghi "Set RUN_RAGAS=1 to enable the slower Ragas pass." |

Baseline đạt 1.000 vì câu hỏi được thiết kế để trả lời chính xác trên dữ liệu sạch: đây là mốc tham chiếu, không phải thước đo năng lực của agent. Mọi mức giảm sau corruption vì thế đều do dữ liệu.

## 8. Data quality và freshness

### Quality checks

| Check        | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline      | Bằng chứng |
| ------------ | ----------------- | ------------------ | ----------------------- | ------------ |
| `expect_table_row_count_to_be_between` (bắt buộc) | Volume | 5 đến 5000 dòng | PASS, quan sát 24 | `data/quality/baseline_quality_report.json` |
| `expect_column_values_to_not_be_null(paper_id)` (bắt buộc) | Completeness | 0 giá trị null | PASS, 0 lỗi | như trên |
| `expect_column_values_to_not_be_null(title)` (bắt buộc) | Completeness | 0 giá trị null | PASS, 0 lỗi | như trên |
| `expect_column_values_to_not_be_null(text_for_embedding)` (bắt buộc) | Completeness | 0 giá trị null | PASS, 0 lỗi | như trên |
| `expect_column_values_to_be_unique(paper_id)` (bắt buộc) | Uniqueness | Không trùng | PASS, 0 lỗi | như trên |
| `expect_column_value_lengths_to_be_between(summary)` (bắt buộc) | Completeness | Tối thiểu 30 ký tự | PASS, 0 lỗi | như trên |
| `expect_column_value_lengths_to_be_between(title)` (bổ sung) | Validity | Tối thiểu 10 ký tự | PASS, 0 lỗi | như trên |
| `expect_column_values_to_not_match_regex(summary)` (bổ sung) | Validity | Không có chuỗi từ 3 ký hiệu `#@$%^&*~\|<>{}[]\` liên tiếp | PASS, 0 lỗi | như trên |

Bốn expectation bắt buộc theo `docs/Guide.md` (row count, not-null trên 3 cột, unique, độ dài `summary`) tạo 6 lượt kiểm tra; hai expectation bổ sung nhắm vào hai kịch bản mà bộ bắt buộc không thấy: tiêu đề bị cắt và ký tự rác. Tổng cộng GX đánh giá 8 expectation, baseline đạt 8/8.

### Freshness

| Thuộc tính               | Giá trị                           |
| -------------------------- | ----------------------------------- |
| Freshness được đo tại | Bảng sạch `data/clean/papers_clean.json` (cột `age_days`, `published`), trước khi index |
| Timestamp mới nhất       | `published` mới nhất 2026-07-22; cũ nhất 2026-03-28; tuổi trung vị 110.5 ngày |
| Ngưỡng freshness         | Dòng quá hạn khi `age_days > 180`; stale khi quá 25% số dòng quá hạn |
| Trạng thái baseline      | Fresh |
| Lý do                     | 1/24 dòng quá hạn (4.2%), dưới ngưỡng 25%; dòng đó là bài 2026-03-28, 181 ngày tuổi tại `run_date` 2026-09-25 |

`success` của báo cáo chỉ phản ánh GX; freshness được ghi bên cạnh, và `gate_passed` là kết hợp của cả hai. Lý do tách: một snapshot sạch vẫn tự trở nên stale khi lịch trôi, và đó là tín hiệu "cần nạp bài mới", không phải "dữ liệu hỏng".

## 9. Corruption scenarios và repair

| Corruption         | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair   |
| ------------------ | ---------- | ---------------------: | ------------------------ | --------------------- | -------------- |
| `drop_latest_records` | Bỏ `int(24 × 0.20)` = 4 bài có `published` mới nhất | 4 | Bài mới nhất lùi về trước | Không expectation nào fail; `latest_published` 2026-07-22 → 2026-06-12; eval_009 và eval_010 mất tài liệu đúng (hit ✗) | Dựng lại từ raw records |
| `blank_summary` | Đặt `summary` thành chuỗi rỗng | 3 | Độ dài `summary` < 30 | `expect_column_value_lengths_to_be_between(summary)` FAIL, 3 dòng; không câu nào hỏi trực tiếp các bài này | Dựng lại từ raw records |
| `inject_text_noise` | Chèn một cụm ký hiệu rác sau mỗi 3 từ của `summary` | 3 | Regex ký hiệu rác | `expect_column_values_to_not_match_regex(summary)` FAIL, 3 dòng; eval_002 hỏi tác giả nên F1 vẫn 1.00 | Dựng lại từ raw records |
| `truncate_title` | Cắt tiêu đề còn 7 ký tự | 3 | Độ dài `title` < 10 | `expect_column_value_lengths_to_be_between(title)` FAIL, 3 dòng; eval_006 trả lời đúng nhưng từ bài khác | Dựng lại từ raw records |
| `stale_date` | Lùi `published` 365 ngày, cộng 365 vào `age_days` | 8 | Freshness SLA fail | Freshness FAIL, 13/24 dòng quá hạn (54.2%); eval_007 (câu hỏi ngày) F1 1.00 → 0.00 | Dựng lại từ raw records |
| `duplicate_rows` | Nhân bản 4 dòng, trùng `paper_id` | 4 | Unique `paper_id` fail | `expect_column_values_to_be_unique(paper_id)` FAIL, 8 dòng (cả hai bản); 4/10 câu có tài liệu lặp trong top-4 | Dựng lại từ raw records |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: Log ghi seed 42, 24 dòng vào và 24 dòng ra, 6 kịch bản, và với mỗi kịch bản có mô tả tiếng Việt, số dòng và danh sách `paper_id` bị tác động. Bốn kịch bản sửa trường (`blank_summary`, `inject_text_noise`, `truncate_title`, `stale_date`) nhắm vào các nhóm dòng không trùng nhau; `duplicate_rows` chọn dòng bất kỳ và trùng `stale_date` ở 3 `paper_id` (`...71803`, `...71811`, `...71817`).

### Phân tích từng kịch bản

- **`drop_latest_records`, silent failure rõ nhất.** Bỏ 4 bài mới nhất rồi `duplicate_rows` thêm 4 dòng, nên bảng vẫn 24 dòng và `expect_table_row_count_to_be_between` PASS với giá trị quan sát 24. Không expectation nào nhìn vào ngày mới nhất; lỗi chỉ lộ qua `latest_published` trong báo cáo freshness và qua metrics. Hai câu hỏi trên bài bị bỏ cho hai kết quả khác nhau. eval_009 (summary): top-1 là bài gần trùng "Advanced Perspectives on Synthetic Corruption Testing" (`...71819`), bài này lại bị `blank_summary`, nên câu trả lời là chuỗi rỗng và F1 0.00. eval_010 (authors): top-1 là "Advanced Perspectives on Continuous Benchmark Evaluation for Enterprise Retrieval Pipelines" (`...71824`), cùng tác giả "Quang Le, Yen Vu", nên F1 vẫn 1.00 dù hit ✗. LLM judge cũng chấm câu này 5/5 với nhận xét "The model answer perfectly matches the reference answer." Câu trả lời đúng nhưng nguồn sai, và cả token F1 lẫn LLM judge đều không thấy, vì cả hai chỉ so câu trả lời với đáp án.
- **`blank_summary`.** GX bắt được cả 3 dòng. Không có ground-truth doc nào thuộc 3 dòng này, nên cột "Câu hỏi bị ảnh hưởng" trong `corruption_report.md` để trống, nhưng kịch bản vẫn gây hại gián tiếp qua eval_009 như trên. `expect_column_values_to_not_be_null(text_for_embedding)` vẫn PASS vì `text_for_embedding` còn các dòng `Title:`, `Authors:`; chỉ expectation độ dài `summary` thấy được lỗi này.
- **`inject_text_noise`.** Regex bắt đủ 3 dòng. Nhiễu được chèn từ câu đầu của `summary`, chính là câu `qa.py` dùng để trả lời câu hỏi summary, nên nếu có câu summary trên các bài này thì F1 sẽ giảm. Câu duy nhất chạm vào (eval_002) hỏi tác giả, nên F1 vẫn 1.00.
- **`truncate_title`.** Expectation độ dài `title` bắt đủ 3 dòng. Với eval_006, tiêu đề bị cắt còn "Automat" nên tra theo tiêu đề thất bại; tìm kiếm ngữ nghĩa xếp bài gần trùng `...71822` (cùng tác giả) lên top-1 và bài đúng `...71810` xuống hạng 3. Hit vẫn ✓ và F1 vẫn 1.00, nên cả hai metric đều không thấy nguồn đã đổi.
- **`stale_date`.** Không có expectation GX nào về ngày; freshness SLA bắt được: 13/24 dòng quá hạn (8 dòng bị lùi, 1 dòng vốn đã quá hạn ở baseline cùng bản nhân của nó, và 3 bản nhân của các dòng bị lùi). Metric chỉ giảm khi trường bị hỏng đúng là trường câu hỏi hỏi tới: eval_007 hỏi ngày và nhận `2025-06-09` thay vì `2026-06-09` (F1 0.00), còn eval_004, eval_005, eval_008 cũng nằm trên bài bị lùi ngày nhưng hỏi categories hoặc summary nên F1 vẫn 1.00.
- **`duplicate_rows`.** Unique `paper_id` bắt được (8 dòng, cả hai bản). Không làm giảm F1 vì `qa.py` trả lời từ top-1, nhưng bản nhân chiếm chỗ trong top-4: eval_001, eval_004, eval_005, eval_010 nhận ngữ cảnh có tài liệu lặp (eval_001 và eval_005 chỉ còn 2 tài liệu khác nhau). Bản nhân còn đẩy số dòng quá hạn lên.

Giải thích cách repair đảm bảo dữ liệu được phục hồi từ nguồn đáng tin cậy thay vì chỉ che kết quả lỗi:

Repair không sửa bảng bẩn. Nó đọc lại `data/raw/crossref_records.json`, file được ghi ở pha 1 và không bước corruption nào chạm tới, rồi chạy lại đúng hàm `build_clean_dataframe` với `run_date` 2026-09-25 đọc từ `run_context.json`. Collection `papers-repaired` bị xóa và tạo lại mỗi lần chạy, nên không còn vector cũ. Bằng chứng: bảng repaired phải qua GX (nếu không flow dừng), và sha256 của bảng repaired (`18f784380c172a51b49d6c79254bcb5b7c0a871dd27c92876a256b07134d7d84`) trùng sha256 bảng baseline trong `repair_idempotency.json`. sha256 tính trên JSON của 16 cột hợp đồng theo đúng thứ tự, nên chỉ cần một giá trị lệch là hash khác.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal            | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét   |
| ------------------------ | -------: | --------: | -------: | -----------------------: | --------------: | ------------ |
| `retrieval_hit_rate`   | 1.000 | 0.800 | 1.000 | -0.200 | 100% (về baseline) | 2 câu miss đều do `drop_latest_records` (eval_009, eval_010) |
| `mean_token_f1`        | 1.000 | 0.800 | 1.000 | -0.200 | 100% (về baseline) | 2 câu F1 0.00: eval_007 (`stale_date`), eval_009 (`drop_latest_records` cộng `blank_summary`) |
| `judge_accuracy`       | 1.000 | 0.800 | 1.000 | -0.200 | 100% (về baseline) | LLM judge (10/10 verdict LLM mỗi trạng thái) đánh `correct: false` cho đúng hai câu có F1 0.00 (eval_007, eval_009); eval_010 vẫn được đánh đúng |
| `mean_judge_score`     | 5.000 | 4.200 | 5.000 | -0.800 | 100% (về baseline) | 8 câu 5 điểm, 2 câu 1 điểm (eval_007, eval_009) |
| Quality checks pass/fail | 8/8 PASS | 4/8 PASS (4 FAIL) | 8/8 PASS | -4 expectation | 100% | FAIL: unique `paper_id`, độ dài `title`, độ dài `summary`, regex `summary` |
| Freshness status         | Fresh, 1/24 (4.2%) | Stale, 13/24 (54.2%) | Fresh, 1/24 (4.2%) | +12 dòng quá hạn | 100% | Bài mới nhất 2026-07-22 → 2026-06-12 → 2026-07-22 |

Kết luận có quan hệ nhân quả:

1. `stale_date` lùi `published` của 8 dòng 365 ngày → freshness SLA chuyển Fresh sang Stale (13/24 dòng quá hạn, vượt ngưỡng 25%) → chỉ câu hỏi về ngày (eval_007) mất điểm, F1 1.00 → 0.00; ba câu khác trên bài bị lùi ngày giữ F1 1.00. Tín hiệu quality nói "dữ liệu cũ", còn metric chỉ giảm ở câu hỏi đúng trường bị hỏng.
2. `drop_latest_records` bỏ 4 bài mới nhất, bị `duplicate_rows` bù lại số dòng → row count vẫn 24, không expectation nào fail, chỉ `latest_published` lùi → hit rate 1.000 → 0.800 (eval_009, eval_010). Đây là kịch bản duy nhất không expectation nào bắt, và eval_010 cho thấy token F1 có thể giữ 1.00, còn LLM judge vẫn chấm 5/5, khi nguồn đã sai.
3. Repair đọc lại raw records với cùng `run_date` → GX 8/8, freshness 1/24, sha256 trùng baseline → cả bốn metric về đúng giá trị baseline. Phục hồi hoàn toàn vì raw records không bị corruption chạm tới và bước làm sạch là hàm tất định của (raw records, `run_date`).

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Manifest embedding do `LocalEmbeddingIndex.build` của code starter ghi ra lưu `persist_path` bằng `str(persist_path)`, tức đường dẫn tuyệt đối tới thư mục `data/chroma` trong hồ sơ người dùng của máy chạy. Manifest này được đọc lại bởi `LocalEmbeddingIndex.load`, là hàm giao diện Streamlit dùng để mở 3 collection. Trên máy khác (máy Tài, máy Long, máy giám khảo), đường dẫn đó không tồn tại; đồng thời rubric trừ 5 điểm khi repo chứa đường dẫn tuyệt đối của máy cá nhân.
- **Nguyên nhân:** `persist_path` lấy từ `settings.paths.chroma_dir`, vốn được dựng từ `Path(__file__).resolve()`, nên luôn là đường dẫn tuyệt đối. Module index và module đọc manifest nằm ở hai phía của ranh giới artifact, nên lỗi không lộ ra khi build và đọc trên cùng một máy.
- **Cách xử lý:** Trong `src/retrieval/index.py`, `build` lưu `persist_path` tương đối theo thư mục gốc project dạng POSIX (`data/chroma`); `load` ghép lại với `settings.paths.project_dir` khi đường dẫn không tuyệt đối.
- **Cách xác minh:** Sau `python script/run_phase1.py` và `python script/run_corruption_flow.py`, ba file `data/embeddings/papers_embeddings.json`, `papers_embeddings_corrupted.json`, `papers_embeddings_repaired.json` đều ghi `"persist_path": "data/chroma"`, với collection lần lượt `papers-baseline`, `papers-corrupted`, `papers-repaired`, mỗi collection 24 document. Kiểm tra trên clone của máy khác: `[CẦN TÀI XÁC NHẬN]`, `[CẦN LONG XÁC NHẬN]`.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng   | Hướng cải thiện có thể kiểm chứng |
| --------------------- | -------------- | ----------------------------------------- |
| Lỗi dữ liệu có sẵn trong snapshot nguồn mà không check nào bắt: cả 12 bài "Advanced Perspectives on …" trong `data/raw/crossref_records.json` (đã có từ `crossref_response.json`) có abstract dạng "An extended empirical study on " cộng abstract của bài gốc cùng tên nhưng mất ký tự đầu, ví dụ "etrieval-Augmented Generation" (`...71813`), "oft-deletions" (`...71815`), "valuating open-domain QA" (`...71817`) | Mọi expectation đều PASS vì văn bản vẫn đủ dài, không null, không có ký hiệu rác. Chữ bị cụt đi thẳng vào index và vào ground truth: eval_005 lấy đáp án "An extended empirical study on valuating open-domain QA requires robust metrics.", nên F1 1.00 của baseline được đo trên một đáp án đã lỗi | Thêm một check dạng cảnh báo so phần abstract nhúng với abstract của bài gốc cùng tiêu đề; trên snapshot hiện tại check này phải gắn cờ đúng 12 dòng. Không sửa tay snapshot, để giữ lineage |
| Không expectation nào bắt `drop_latest_records` khi số dòng được bù lại | Mất dữ liệu mới nhất đi qua gate | Thêm expectation trên giá trị lớn nhất của `published` (ví dụ không được lùi so với lần chạy trước, ghi trong `run_context.json`); chạy lại corruption flow và xác nhận kịch bản này chuyển sang "đã bắt" |
| Hit rate tính trúng khi tài liệu đúng nằm bất kỳ đâu trong top-4, còn câu trả lời lấy từ top-1; token F1 và LLM judge chỉ so câu trả lời với đáp án | eval_006 trả lời đúng từ bài khác mà hit, F1 và judge đều đạt; eval_010 F1 1.00 và judge 5/5 dù hit ✗ | Thêm metric "nguồn top-1 là tài liệu đúng"; trên artifact hiện tại metric này phải giảm ở eval_006, eval_009, eval_010 |
| 10 câu hỏi không phủ mọi dòng bị hỏng | `blank_summary` không có câu hỏi trực tiếp; nhiễu `summary` không gặp câu summary nào | Sinh thêm câu hỏi nhắm vào dòng của từng kịch bản trong `corruption_log.json`, giữ file test set cố định cho cả ba trạng thái |
| Windows Application Control trên máy tác giả chặn DLL của scikit-learn 1.9.0 (bản ghim trong `uv.lock`, là dependency của sentence-transformers) | `uv sync` trên máy đó cài bản bị chặn, import thất bại | Máy tác giả ghim 1.7.2 trong `.venv`, không sửa `uv.lock` của nhóm; tái hiện trên máy không có chính sách này để xác nhận lockfile chạy nguyên trạng `[CẦN TÀI XÁC NHẬN]` |
| Chạy từ snapshot offline | Bảng baseline tự trôi về stale khi lịch trôi, dù dữ liệu không đổi | Dùng `RUN_DATE=2026-09-25` để tái hiện đúng số liệu; chạy `REFRESH_SOURCE=1` để lấy dữ liệu mới khi cần đo trên nguồn sống |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp. (Lần chạy chính thức trên máy Việt lúc 08:39 và 08:42 UTC; phần tái hiện trên máy Tài và máy Long chờ xác nhận.)
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [ ] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.
