# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
| --- | --- |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | `logitech` |
| Repository | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | 2026-09-25 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | GitHub | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- | --- |
| 1 | Lò Văn Long | 2A202602541 | `getlmt` | Corruption & Integration owner | `src/ingestion/corruption.py`, `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py`, `src/pipelines/common.py`, `tests/`, `script/run_tests.py` |
| 2 | Nguyễn Như Tài | 2A202602976 | `nntai1111` | Data Ingestion & Cleaning owner | `src/ingestion/crossref.py`, `src/ingestion/cleaning.py`, `data/raw/` |
| 3 | Hoàng Quốc Việt | 2A202602563 | `Catnip-harvest` | Evaluation & Observability owner | `src/evaluation/testset.py`, `src/observability/quality.py`, `src/observability/reporting.py` |

## 2. Tóm tắt kết quả

**Tóm tắt của nhóm:**

Nhóm hoàn thiện cả 8 module khung. Hai entrypoint `script/run_phase1.py` và `script/run_corruption_flow.py` đều chạy thành công (exit code 0).

**Pha baseline:**
- Nạp 24 bài báo từ snapshot Crossref và làm sạch thành 24 dòng.
- Quality gate Great Expectations 1.x đạt 12/12 expectation; freshness FRESH (1/24 bài quá 180 ngày).
- Index 24 vector vào ChromaDB `papers-baseline`.
- Đạt hit rate 1.000 và token F1 1.000 trên bộ test cố định 10 câu.

**Pha corruption:** tiêm 6 lỗi, dữ liệu còn 22 dòng với 19 paper duy nhất. Pipeline vẫn chạy không báo lỗi, nhưng hit rate giảm còn 0.800, token F1 còn 0.745 và judge accuracy còn 0.800. Đây chính là *silent failure*. Hai lỗi ảnh hưởng rõ nhất:
- *Drop latest records*: 2 câu mất retrieval hit. Riêng `eval_001` vẫn được LLM judge chấm đúng, dù nội dung lấy từ một paper khác gần giống.
- *Stale date*: câu hỏi về ngày xuất bản trả lời sai hoàn toàn.

**Phát hiện:** quality gate bắt được 5 kịch bản (7/12 expectation đạt). Freshness SLA bắt kịch bản còn lại (31.8% dòng stale, vượt ngưỡng 25%).

**Repair:** tự động kích hoạt và dựng lại dữ liệu từ raw snapshot. Fingerprint dữ liệu trùng với baseline qua 2 lần chạy, và mọi chỉ số phục hồi 100%.

**Giới hạn chính:** benchmark chỉ có 10 câu nên lỗi *truncate title* không làm đổi metric nào. Quota free của Gemini rất thấp (`gemini-2.5-flash` chỉ 20 request/ngày), nên nhóm dùng `gemini-3.5-flash-lite`, kèm cơ chế exact-match và cache cho LLM judge.

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
Crossref API (live, REFRESH_SOURCE=1) hoặc snapshot data/raw/crossref_response.json
    -> raw response (giữ nguyên byte) + raw records + ingestion_manifest (SHA-256, mode)
    -> cleaning & data modeling (age_days, text_for_embedding, dedupe theo paper_id)
    -> QUALITY GATE: Great Expectations 1.x + freshness SLA   (fail -> dừng, không index)
    -> embedding all-MiniLM-L6-v2 + ChromaDB `papers-baseline`
    -> evaluation baseline trên test set cố định (hit rate, token F1, LLM judge)
    -> corruption 6 kịch bản (seed 42) -> gate phát hiện -> index `papers-corrupted` -> re-evaluate
    -> auto-repair từ data/raw/crossref_records.json -> gate lại -> index `papers-repaired` -> re-evaluate
    -> corruption_report.md: đối chiếu baseline / corrupted / repaired
```

### Trách nhiệm của từng khối

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref `/works` hoặc snapshot | Parse JATS/HTML, chuẩn hoá DOI/tác giả/ngày; retry 429/5xx; fallback snapshot | `data/raw/crossref_records.json`, `data/raw/ingestion_manifest.json` | Tài |
| Cleaning | `list[PaperRecord]`, run date | Chuẩn hoá, lọc bản ghi lỗi, dedupe, `age_days`, `text_for_embedding` | `data/clean/papers_clean.csv`, `.json` | Tài |
| Embedding/index | Clean dataframe | MiniLM (normalize) → ChromaDB cosine, 3 collection tách biệt | `data/chroma/`, `data/embeddings/*.json` | Long (điều phối; module `retrieval/` có sẵn) |
| Evaluation | Clean dataframe, test set | 10 câu / 4 loại; hit rate, token F1, LLM judge | `data/eval/test_set.json`, `data/results/*_metrics.json` | Việt |
| Observability | Dataframe mỗi trạng thái | GX 1.x (12 expectation), freshness SLA | `data/quality/*.json`, `data/quality/gx/*.json` | Việt |
| Corruption/repair | Clean dataframe / raw snapshot | 6 kịch bản có seed; repair từ raw, fingerprint | `corruption_log.json`, `repair_log.json`, `papers_clean_{corrupted,repaired}.*` | Long (repair dùng quy tắc cleaning của Tài) |
| Orchestration | `Settings` | `phase1.py`, `corruption_flow.py` | `data/reports/*.md`, metrics | Long |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` | `gemini` |
| `LLM_MODEL` | `gemini-3.5-flash-lite` |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 (snapshot offline, `REFRESH_SOURCE` không bật) |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày; cảnh báo khi > 25% dòng stale |
| Random seed | 42 (corruption) |

Không dán nội dung API key hoặc file `.env` vào báo cáo.

### Lệnh cài đặt

```bash
uv sync --extra dev
```

Hoặc:

```bash
python -m pip install -e ".[dev]"
```

### Lệnh chạy

```bash
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
uv run python script/run_tests.py     # 83 test, coverage 97%, chạy offline
```

### Kết quả tái hiện

| Lệnh | Trạng thái | Thời điểm chạy gần nhất | Bằng chứng |
| --- | --- | --- | --- |
| Baseline pipeline | Thành công (exit 0, ~23 giây) | 2026-09-25 09:24 UTC | `data/reports/phase1_report.md`, `data/results/baseline_metrics.json` |
| Corruption flow | Thành công (exit 0, ~15 giây) | 2026-09-25 09:25 UTC | `data/reports/corruption_report.md`, `data/results/repair_log.json` |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref REST API `https://api.crossref.org/works` (snapshot `data/raw/crossref_response.json`) |
| Query/filter | `agentic retrieval augmented generation large language model`; `from-pub-date:<ngày chạy − 180 ngày>,has-abstract:true` |
| Thời điểm lấy dữ liệu | Snapshot của repo; lần nạp gần nhất 2026-09-25 09:24 UTC, mode `snapshot` (xem `data/raw/ingestion_manifest.json`) |
| Số record nhận được | 24 item → 24 record hợp lệ |
| Cơ chế retry/backoff | Tối đa 4 lần cho 429/500/502/503/504 và lỗi mạng; chờ `Retry-After` hoặc 2s·2^(n−1) (≤ 30s); thất bại thì fallback snapshot, snapshot cũ được lưu vào `data/raw/archive/` trước khi ghi đè |

### Raw và clean schema

| Trường | Kiểu dữ liệu | Bắt buộc? | Ý nghĩa | Xử lý khi thiếu/sai |
| --- | --- | --- | --- | --- |
| `paper_id` | str | Có | DOI chuẩn hoá (lowercase, bỏ tiền tố `https://doi.org/`) | Loại bản ghi |
| `title` | str | Có | Tiêu đề đã bỏ markup | Loại nếu rỗng hoặc < 8 ký tự |
| `summary` | str | Có | Abstract đã bỏ thẻ JATS | Loại nếu < 30 ký tự |
| `authors` / `authors_joined` | list[str] / str | Không | Danh sách tác giả `given family` | Dedupe; rỗng thì chuỗi rỗng |
| `categories` / `categories_joined` | list[str] / str | Không | `subject` của Crossref | Fallback `type`, rồi `Uncategorized` |
| `published` | str `YYYY-MM-DD` | Có | Ngày xuất bản sớm nhất có trong record | Loại nếu không parse được ISO 8601 |
| `updated` | str `YYYY-MM-DD` | Không | Ngày deposit/created | Fallback `published` |
| `age_days` | int | Có | `(run_date − published).days` | Tính lại mỗi lần chạy |
| `text_for_embedding` | str | Có | 5 dòng Title/Authors/Published/Categories/Summary | Sinh lại sau mọi thay đổi |
| `abs_url`, `pdf_url` | str | Không | Link DOI / PDF | `pdf_url` fallback `abs_url` |

### Quy tắc cleaning

| Quy tắc | Quality dimension liên quan | Số record bị tác động | Cách xác minh |
| --- | --- | --: | --- |
| Loại record thiếu `paper_id`, title < 8, summary < 30, ngày lỗi | Completeness / Validity | 0 (snapshot sạch) | `tests/test_cleaning.py::test_invalid_rows_are_dropped_and_latest_duplicate_wins` |
| Dedupe theo `paper_id`, giữ bản `updated` mới nhất | Uniqueness | 0 | Cùng test trên; GX `paper_id_unique` |
| Chuẩn hoá khoảng trắng, bỏ JATS/HTML, decode entity | Validity / Consistency | 1 abstract có khoảng trắng kép | `tests/test_crossref.py::test_parser_reproduces_committed_records` |
| Tính `age_days` theo run date (UTC) | Timeliness | 24 | `data/quality/freshness_report.json` |

`text_for_embedding` ghép 5 trường theo đúng thứ tự Title → Authors → Published → Categories → Summary, để embedding thấy đủ ngữ cảnh. Document ID là DOI chuẩn hoá (`paper_id`), dùng chung cho index, test set và quality gate. Collection Chroma dùng `record_id = paper_id::vị trí` nên bản trùng vẫn index được, và việc trùng lặp đó được gate `paper_id_unique` phát hiện. `age_days` tính từ `published` đến thời điểm chạy, nên freshness là tín hiệu phụ thuộc thời gian.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 10 |
| Các `question_type` | `summary` 3, `authors` 3, `date` 2, `categories` 2 |
| Ground-truth document ID | `paper_id` của 10 paper trải đều theo ngày xuất bản (vị trí 0, 3, 5, …, 23) |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection | ChromaDB persistent `data/chroma`, cosine; `papers-baseline` / `papers-corrupted` / `papers-repaired` |
| Retrieval `top_k` | 4 |
| LLM provider/model | `gemini` / `gemini-3.5-flash-lite` (LLM judge + demo agent) |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json` (tái sử dụng, chỉ sinh lại khi `REFRESH_TEST_SET=1`) |

Test set được giữ nguyên cho cả 3 trạng thái để mọi thay đổi metric chỉ có thể đến từ dữ liệu. Nếu sinh lại test set từ dữ liệu hỏng, ground truth sẽ hỏng theo và che mất suy giảm. Câu hỏi đặt tiêu đề trong dấu nháy đơn và dùng cụm "who authored" / "when was" / "what categories", để `retrieval/qa.py` chọn đúng trường trả lời (có test `test_questions_select_the_matching_answer_field_in_qa`).

## 7. Kết quả baseline

### Artifact checklist

| Artifact | Đường dẫn thực tế | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| Raw response/records | `data/raw/` | Có | + `ingestion_manifest.json` |
| Cleaned dataset | `data/clean/` | Có | CSV (list lưu dạng JSON string) + JSON |
| Embedding manifest/index | `data/embeddings/` | Có | 3 manifest + `data/chroma/` |
| Evaluation set | `data/eval/` | Có | 10 câu |
| Baseline metrics | `data/results/baseline_metrics.json` | Có | Kèm breakdown theo loại câu hỏi |
| Quality/freshness | `data/quality/` | Có | Báo cáo tóm tắt + kết quả GX gốc trong `gx/` |
| Baseline report | `data/reports/phase1_report.md` | Có | |

### Baseline metrics

| Metric | Giá trị | Diễn giải |
| --- | --: | --- |
| `retrieval_hit_rate` | 1.000 | Cả 10 paper ground truth đều có trong top-4 |
| `mean_token_f1` | 1.000 | Câu trả lời trích xuất trùng nguyên văn ground truth |
| `judge_accuracy` | 1.000 | 10/10 đúng; cả 10 câu khớp nguyên văn nên không cần gọi LLM |
| `mean_judge_score` | 5.000 | |
| Ragas, nếu có | N/A | Bỏ qua mặc định (`RUN_RAGAS=1` để bật) vì chậm và tốn quota LLM |

Baseline đạt mức trần là đúng thiết kế: `qa.py` trích câu trả lời từ metadata của tài liệu top-1, còn ground truth sinh từ cùng các trường của dữ liệu sạch. Baseline vì vậy là mức tham chiếu để đo suy giảm do dữ liệu.

## 8. Data quality và freshness

### Quality checks

| Check | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline | Bằng chứng |
| --- | --- | --- | --- | --- |
| `schema_columns` | Schema | Có đủ 16 cột clean schema | Pass | `data/quality/baseline_quality_report.json` |
| `row_count` (bắt buộc) | Volume | 5–5000 dòng | Pass (24) | như trên |
| `paper_id/title/text_for_embedding_not_null` (bắt buộc) | Completeness | 0 null | Pass (0/24) | như trên |
| `paper_id_unique` (bắt buộc) | Uniqueness | Không trùng | Pass (0/24) | như trên |
| `summary_min_length` (bắt buộc) | Validity | ≥ 30 ký tự | Pass (0/24) | như trên |
| `title_min_length` | Validity | ≥ 8 ký tự | Pass (0/24) | như trên |
| `summary_no_noise` | Validity | Không có chuỗi ký hiệu rác `[#@$%^&*~|]{2,}` | Pass (0/24) | như trên |
| `paper_id_is_doi` | Validity | Regex `^10\.\d{4,9}/\S+$` | Pass (0/24) | như trên |
| `published_iso_date` | Validity | `YYYY-MM-DD` | Pass (0/24) | như trên |
| `source_papers_present` | Completeness (đối soát nguồn) | Chứa mọi `paper_id` của raw snapshot | Pass (24/24) | như trên |

Kết quả GX gốc nằm ở `data/quality/gx/baseline_validation_result.json`. Gate chạy **trước** khi index: nếu fail, `run_phase1.py` dừng và không đưa dữ liệu vào vector store.

### Freshness

| Thuộc tính | Giá trị |
| --- | --- |
| Freshness được đo tại | Clean dataset (cột `age_days`) |
| Timestamp mới nhất | `published` mới nhất 2026-07-22 (65 ngày) |
| Ngưỡng freshness | 180 ngày; tối đa 25% dòng stale |
| Trạng thái baseline | Fresh |
| Lý do | 1/24 dòng (4.2%) quá 180 ngày, thấp hơn ngưỡng 25% |

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair |
| --- | --- | --: | --- | --- | --- |
| Drop latest records | Bỏ 20% bài mới nhất | 5 | `source_papers_present`, `latest_published` lùi | Gate fail (19/24 paper); latest 2026-07-22 → 2026-06-12; `eval_001`, `eval_002` mất hit | Dựng lại từ raw |
| Blank summary | `summary = ""` | 3 | `summary_min_length` | Gate fail (3 dòng); `eval_008` (categories) không đổi | Dựng lại từ raw |
| Inject noise | Chèn token rác vào summary | 3 | `summary_no_noise` | Gate fail; F1 `eval_005` 0.82, `eval_009` 0.89 | Dựng lại từ raw |
| Truncate title | Cắt còn 7 ký tự | 3 | `title_min_length` | Gate fail (4 dòng, tính cả bản trùng); không câu hỏi nào bị ảnh hưởng | Dựng lại từ raw |
| Stale date | `published` − 365 ngày | 7 | Freshness SLA | STALE 31.8%; `eval_007` trả lời 2025 thay vì 2026 | Dựng lại từ raw |
| Duplicate rows | Nhân đôi dòng | 3 | `paper_id_unique` | Gate fail (6 dòng); `eval_003`, `eval_004` không đổi | Dựng lại + dedupe |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: log ghi đủ 6 loại, gồm tham số, số dòng, danh sách `paper_id`, check kỳ vọng phát hiện và ví dụ trước/sau.

Repair không sửa trên dữ liệu hỏng. Pipeline đọc lại `data/raw/crossref_records.json`, kiểm tra lineage với `crossref_response.json` (khớp), rồi áp đúng quy tắc cleaning của baseline. Dữ liệu sau đó phải qua lại gate (12/12) mới được index. Để chứng minh tính idempotent, repair chạy hai lần: SHA-256 nội dung của cả hai lần (`a9364c4a…`) trùng nhau và trùng baseline, trong khi dữ liệu hỏng có fingerprint khác (`556b513e…`). Toàn bộ nằm trong `data/results/repair_log.json`.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét |
| --- | --: | --: | --: | --: | --: | --- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | −0.200 | 100% | 2 paper ground truth bị drop |
| `mean_token_f1` | 1.000 | 0.745 | 1.000 | −0.255 | 100% | drop + noise + stale date |
| `judge_accuracy` | 1.000 | 0.800 | 1.000 | −0.200 | 100% | `eval_002`, `eval_007` sai |
| `mean_judge_score` | 5.000 | 4.200 | 5.000 | −0.800 | 100% | 5 câu lệch được LLM chấm |
| Quality checks pass/fail | 12/12 pass | 7/12 pass | 12/12 pass | −5 check | 100% | 5 check fail đúng loại lỗi |
| Freshness status | FRESH (4.2%) | STALE (31.8%) | FRESH (4.2%) | +27.6 điểm % stale | 100% | stale date + drop latest |

Chuỗi nguyên nhân–hệ quả (đầy đủ trong `data/reports/corruption_report.md` §6):

1. **Drop latest records → `source_papers_present` fail (19/24), `latest_published` lùi → retrieval hit 1.0 → 0.8.** Nguy hiểm nhất là `eval_001`: paper gốc đã mất nên hit ❌, nhưng hệ thống lấy câu gần giống từ một paper "Advanced Perspectives…" khác (F1 0.74), và LLM judge vẫn chấm đúng (5/5). Metric chất lượng câu trả lời không bắt được lỗi này; chỉ retrieval hit và gate đối soát nguồn cho thấy dữ liệu đã mất.
2. **Stale date (7 dòng) → freshness 4.2% → 31.8% (STALE) → câu hỏi ngày của `eval_007` sai (F1 0, judge 1/5).** Sau **repair từ raw**, gate đạt 12/12, freshness về 4.2%, và cả 4 metric trở về đúng baseline (mức phục hồi 100%) với fingerprint trùng khớp.

Không phải lỗi nào cũng làm đổi metric. *Truncate title* không trúng paper nào trong test set, còn *blank summary* và *duplicate rows* chỉ trúng các câu hỏi dùng trường khác. Tất cả vẫn bị quality gate phát hiện, vì gate kiểm tra toàn bộ dataset chứ không chỉ 10 paper của benchmark.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** lần chạy corruption flow đầu tiên mất khoảng 10 phút, và 4/10 câu ở trạng thái corrupted bị chấm bằng heuristic fallback thay vì LLM. Pipeline vẫn báo thành công, nên điểm judge giữa các trạng thái lẫn giữa hai cách chấm. Bản thân đây là một *silent failure* ở tầng evaluation.
- **Nguyên nhân:** quota free tier của `gemini-2.5-flash` chỉ 20 request/ngày/model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). `_judge_answer` ban đầu nuốt mọi lỗi và fallback im lặng. Mỗi lượt gọi lỗi mất khoảng 37 giây do client LangChain tự retry.
- **Cách xử lý:** trong `evaluation/metrics.py`:
  - Câu trả lời khớp nguyên văn đáp án được chấm 5 điểm mà không gọi LLM.
  - Verdict của LLM được cache trong `data/results/judge_cache.json`, khoá theo provider, model và prompt.
  - Có retry cho lỗi thoáng qua, và circuit breaker khi gặp `RESOURCE_EXHAUSTED`.
  - Mỗi câu ghi `judge_source` (`llm` / `cache` / `exact_match` / `fallback`), và báo cáo hiển thị nguồn chấm.
  - Nhóm chuyển sang `gemini-3.5-flash-lite` (quota riêng).
- **Cách xác minh:** chạy lại `script/run_corruption_flow.py` cho metric giống hệt lần trước, `judge_mode` gồm cache 5 và exact match 5, fallback 0, thời gian còn khoảng 15 giây. `tests/test_metrics.py` phủ đủ các nhánh exact/cache/retry/quota/fallback.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
| --- | --- | --- |
| Test set chỉ 10 câu / 10 paper, câu hỏi luôn kèm tiêu đề | *Truncate title* không làm đổi metric; retrieval gần như luôn đúng nhờ tra cứu chính xác theo tiêu đề | Mở rộng test set phủ cả 24 paper và thêm câu hỏi ngữ nghĩa không kèm tiêu đề; đo hit rate theo từng loại lỗi |
| QA dạng trích xuất, baseline là mức trần | Chưa đo chất lượng câu trả lời do LLM sinh | Đánh giá câu trả lời của agent; bật `RUN_RAGAS=1` để đo faithfulness và context precision |
| Corpus có nhiều paper "Advanced Perspectives…" gần trùng nội dung | Khi paper gốc mất, retrieval trả về paper "anh em" và judge vẫn chấm đúng (`eval_001`) | Thêm check near-duplicate (cosine > 0.95 giữa embedding) vào gate; báo cáo số cặp gần trùng |
| Snapshot cố định, `age_days` tính theo ngày chạy | Từ khoảng cuối tháng 11/2026, baseline sẽ tự chuyển STALE (> 25% bài quá 180 ngày) | Chạy `REFRESH_SOURCE=1` định kỳ; theo dõi `stale_ratio` theo thời gian |
| Quota LLM miễn phí rất thấp | Demo agent tốn khoảng 6 request mỗi lần chạy pha 1 | Dùng `SKIP_AGENT_DEMO=1` khi không cần demo; judge đã có exact-match và cache |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [ ] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng (`report/<MSSV>_HoTen.md` — phần cá nhân do từng người tự viết).
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.

> Ghi chú: nhóm dùng trợ lý AI (Claude Code) để hỗ trợ viết code, test và tài liệu, theo chính sách AI tại `docs/RULES.md` §3. Mọi số liệu trong báo cáo được sinh từ lần chạy thực tế của hai script. Mỗi thành viên chịu trách nhiệm hiểu và giải thích phần mình phụ trách.
