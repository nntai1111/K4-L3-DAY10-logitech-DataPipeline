# Member Role Report — Day 10: Data Pipeline & Data Observability

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
| Làm một bản thử nghiệm trên nhánh `feat/viet-pipeline` để thử trước các check và các kịch bản lỗi: nạp snapshot Crossref, cleaning, gate GX 1.x + freshness SLA, 6 kịch bản corruption, repair idempotent, test set 10 câu và các báo cáo. | Cả nhóm | Hai điều rút ra từ bản thử nghiệm có trong `quality.py` trên main: check `source_papers_present` (mục 5) và cách ghép kết quả GX theo `check_id` (mục 6). |
| Làm một app demo Streamlit trên bản thử nghiệm: agent trợ lý nghiên cứu trả lời trên ChromaDB, tab "Silent failure" đặt dữ liệu sạch và dữ liệu hỏng cạnh nhau, tab observability, và phần nạp trực tiếp (agent lấy bài mới từ Crossref, bài chỉ được index sau khi qua quality gate). | Cả nhóm, làm công cụ minh hoạ | Cho thấy trực quan hai ý chính của bài: dữ liệu hỏng vẫn cho ra câu trả lời trông bình thường, và gate phải đứng trước vector store. |

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
- 4 loại bắt buộc (6 expectation, vì not null áp cho 3 cột): row count 5–5000; not null cho `paper_id`, `title`, `text_for_embedding`; unique `paper_id`; summary ≥ 30 ký tự.
- 6 check mở rộng, mỗi check nhắm một loại lỗi: schema, title ≥ 8, regex ký hiệu rác, regex DOI, ngày ISO, và đối soát `paper_id` với raw snapshot. Tổng cộng 6 + 6 = 12 expectation.
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

Thêm check đối soát nguồn `source_papers_present` để bắt lỗi mất bản ghi.

- **Bối cảnh:** Khi chạy bản thử nghiệm của mình, tôi thấy kịch bản `drop_latest_records` (bỏ 20% bài mới nhất) không bị expectation theo dòng nào bắt. Lý do rất đơn giản: mỗi dòng còn lại đều hợp lệ nếu xét riêng, nên not null, unique, độ dài hay regex đều pass. Check theo dòng không thể nhìn thấy một dòng đã không còn nữa. Trên main, kịch bản này bỏ 5 bài (step 1 trong `data/results/corruption_log.json`).
- **Các phương án đã cân nhắc:**
  1. Siết `row_count`. Ngưỡng bắt buộc 5–5000 quá rộng. Nếu đặt đúng bằng 24 thì gate sẽ hỏng mỗi khi nguồn thay đổi hợp lệ. Thêm nữa, lỗi nhân bản dòng bù lại số dòng: trên main mất 5 bài nhưng số dòng chỉ giảm từ 24 xuống 22, vì có 3 dòng trùng được thêm vào.
  2. Dựa vào freshness. SLA đo tỉ lệ bài cũ, mà bỏ bài mới thì phần còn lại vẫn chủ yếu là bài mới, nên tỉ lệ này gần như không đổi. `latest_published` có lùi từ `2026-07-22` về `2026-06-12`, nhưng chỉ thấy được khi so với baseline, và không cho biết thiếu bài nào.
  3. Đối soát `paper_id` với raw snapshot: lấy `data/raw/crossref_records.json`, cho chạy qua đúng quy tắc cleaning để ra danh sách `paper_id` bắt buộc phải có, rồi kiểm tra dataset có chứa đủ danh sách đó không.
- **Phương án đã chọn:** phương án 3, thành check mở rộng `source_papers_present` (`_expected_source_ids` dựng danh sách, `ExpectColumnDistinctValuesToContainSet` trên cột `paper_id` kiểm tra). Check này không thuộc 4 loại bắt buộc, nhưng `success` của GX tính trên cả suite, nên nó fail thì gate vẫn fail.
- **Lý do:** Trong ba cách, đây là cách duy nhất hỏi thẳng câu "có thiếu bài nào không" và chỉ ra được bài nào thiếu, không phụ thuộc vào số dòng hay ngày xuất bản. Cái giá phải trả: mỗi lần chạy gate phải dựng lại dataframe sạch từ raw (chỉ 24 bản ghi nên rất nhẹ), và check chỉ tốt bằng raw snapshot. Không có file raw thì check bị bỏ qua (test `test_gate_without_raw_snapshot_skips_source_reconciliation`), còn nếu bản ghi đã mất ngay từ lúc nạp thì đối soát cũng không thấy.
- **Bằng chứng quyết định phù hợp:** trong `data/quality/corrupted_quality_report.json`, `row_count` vẫn pass với 22 dòng, còn `source_papers_present` fail với `19/24 source papers present` và `missing_count` = 5. Năm `paper_id` bị báo thiếu trùng đúng với 5 bài ở step 1 của corruption log. Baseline và repaired đều là `24/24`.

## 6. Một lỗi hoặc blocker đã xử lý

Báo cáo gate gắn sai tên check vì Great Expectations 1.x không trả kết quả theo thứ tự expectation. Lỗi này tôi gặp ở bản thử nghiệm của mình.

- **Triệu chứng/lỗi nguyên văn:** không có lỗi nguyên văn nào để trích, vì không có exception hay traceback: gate chạy xong bình thường. Triệu chứng nằm trong báo cáo: tên các check bị đánh dấu fail không khớp với lỗi tôi vừa tiêm, và nhãn bắt buộc/mở rộng cũng bị gắn sai theo.
- **Lệnh hoặc bước tái hiện:** chạy gate trên dataframe đã tiêm lỗi, rồi so danh sách check fail trong báo cáo với từng kịch bản trong corruption log. Ví dụ đã tiêm blank summary thì phải thấy `summary_min_length` fail, không phải một check khác.
- **Nguyên nhân gốc:** code của tôi ghép kết quả với expectation theo vị trí, tức là coi kết quả thứ i là của expectation thứ i được thêm vào suite. GX 1.x không giữ thứ tự đó. Trên main vẫn nhìn thấy được điều này: trong `data/quality/gx/corrupted_validation_result.json`, kết quả bị gom theo cột, kết quả thứ 4 là `expect_column_values_to_be_unique` trên `paper_id`, trong khi expectation thứ 4 thêm vào suite là `title_not_null`. Nếu ghép theo vị trí, lỗi trùng `paper_id` sẽ bị báo thành "title bị null".
- **Cách xử lý:** ở bản thử nghiệm, tôi bỏ cách ghép theo vị trí và ghép bằng một khoá ổn định là loại expectation + tên cột. `quality.py` trên main làm chắc hơn một bước: lúc tạo suite, mỗi expectation được gắn `meta = {"check_id": ...}` (`_build_checks`); khi đọc kết quả, `run_data_quality_checks` lấy `expectation_config.meta.check_id` của từng kết quả để tìm lại đúng check, rồi mới sắp lại theo thứ tự suite cho dễ đọc. `check_id` tốt hơn loại + cột vì sau này có thể có hai check cùng loại trên cùng một cột (ví dụ hai regex trên `summary`).
- **Cách xác minh sau khi sửa:** chạy lại gate trên dữ liệu hỏng và đối chiếu từng kịch bản. Trên main, lần chạy `python script/run_corruption_flow.py` cho ra `data/reports/corruption_report.md` §4 với 6/6 kịch bản được phát hiện, và mỗi kịch bản khớp đúng tín hiệu dự kiến trong `detected_by` của log: blank summary → `summary_min_length`, inject noise → `summary_no_noise`, truncate title → `title_min_length`, duplicate rows → `paper_id_unique`, drop latest → `source_papers_present`, stale date → `freshness_sla`. Test `test_each_defect_trips_its_dedicated_check` trong `tests/test_quality.py` giữ cho điều này không bị hỏng lại: mỗi lỗi đơn lẻ phải làm đúng check của nó fail, tìm theo `check_id`.
- **Điều học được:** không dựa vào thứ tự kết quả mà thư viện trả về; tự gắn ID của mình vào từng check rồi ghép theo ID. Lớp observability cũng có thể sai một cách im lặng giống như dữ liệu, nên chính báo cáo của gate cũng cần có test.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

1. **Từ Crossref đến vector index.** Ở chế độ live (`REFRESH_SOURCE=1`), `crossref.fetch_source_records` gọi Crossref REST API (`https://api.crossref.org/works`), có retry cho 429/5xx. Mặc định, hoặc khi API lỗi, nó đọc snapshot đã commit; lần chạy trên main dùng chế độ `snapshot` với 24/24 item hợp lệ. Payload gốc được giữ nguyên byte ở `data/raw/crossref_response.json`, còn bản đã parse (bỏ thẻ JATS, chuẩn hoá DOI, tác giả, ngày) nằm ở `data/raw/crossref_records.json`. Sau đó `cleaning.build_clean_dataframe` chuẩn hoá khoảng trắng, loại dòng hỏng, khử trùng theo `paper_id`, tính `age_days` theo ngày chạy và ghép `text_for_embedding` 5 dòng, ra 24 dòng 16 cột. Đến đây là phần của tôi: gate GX và freshness chạy trên dataframe này, gate fail thì `phase1` dừng luôn, không index. Gate pass thì `LocalEmbeddingIndex.build` embed `text_for_embedding` bằng `all-MiniLM-L6-v2` và ghi 24 document vào collection `papers-baseline` trong `data/chroma/`, kèm metadata (title, authors, published, categories, summary) để `qa.py` trích câu trả lời.
2. **Evaluation set và ground-truth document IDs.** Mỗi câu trong `data/eval/test_set.json` có hai loại đáp án. `ground_truth` là giá trị đúng của trường mà `qa.py` sẽ trích (câu đầu của summary, authors, published hoặc categories). `ground_truth_doc_ids` là `paper_id` của bài chứa đáp án. Hai thứ này đo hai việc khác nhau: `retrieval_hit_rate` chỉ hỏi "bài đúng có nằm trong top-k không" (`top_k` = 4), tức là đo retrieval; còn `mean_token_f1` và LLM judge so câu trả lời với `ground_truth`, tức là đo câu trả lời. Phải tách ra vì câu trả lời có thể đúng chữ mà sai nguồn. Ở bản thử nghiệm tôi đã gặp một câu như vậy, và trên main nó lặp lại ở `eval_001` trạng thái corrupted: bài đúng (`10.1145/3637528.3671812`) đã bị drop, hệ thống lấy câu gần giống từ bài `10.1145/3637528.3671824`, hit = false nhưng token F1 vẫn 0.74 và judge chấm 5/5, đúng. Chỉ có `ground_truth_doc_ids` làm lộ ra lỗi này.
3. **Quality checks khác freshness monitoring ở đâu.** Quality check (GX) hỏi "dữ liệu có đúng luật không", với các luật không phụ thuộc thời gian: có null không, có trùng không, độ dài, regex, schema, có đủ bài so với raw không. Fail là chặn: `phase1` không index. Freshness hỏi "dữ liệu còn mới không" so với ngày chạy: dòng có `age_days > 180` là stale, cả tập là STALE khi hơn 25% dòng stale. Trong `phase1` freshness chỉ in cảnh báo chứ không chặn, còn trong `corruption_flow` trạng thái STALE cũng đủ để kích hoạt repair (`gate_failed = not success or not is_fresh`). Hai lớp này bù cho nhau: bài bị lùi 365 ngày vẫn có ngày đúng định dạng ISO nên `published_iso_date` pass, chỉ freshness bắt được (7/22 dòng stale, 31.8%). Ngược lại, freshness không thấy summary rỗng hay dòng trùng.
4. **Vì sao dùng cùng test set cho baseline, corrupted và repaired.** Để thứ duy nhất thay đổi giữa ba lần đo là dữ liệu. Nếu đổi câu hỏi thì metric giảm có thể do câu khó hơn chứ không phải do dữ liệu hỏng. Sinh test set từ dữ liệu hỏng còn tệ hơn: 5 bài đã mất sẽ biến khỏi test set, ground truth sẽ lấy luôn giá trị sai (ví dụ ngày `2025-06-03` thay vì `2026-06-03` của `eval_007`), và trạng thái corrupted sẽ trông hoàn hảo. Vì vậy test set được sinh một lần từ dữ liệu sạch rồi giữ cố định: `load_or_build_test_set` tái sử dụng file cũ trong `phase1`, còn `corruption_flow` đọc thẳng `data/eval/test_set.json` cho cả corrupted và repaired chứ không sinh lại.
5. **Repair được xem là thành công dựa trên gì.** Tôi coi repair thành công khi ba nhóm bằng chứng cùng khớp. Về dữ liệu: `data/results/repair_log.json` có `idempotent: true`, `matches_baseline: true`, fingerprint của hai lần repair đều bằng fingerprint baseline (`a9364c4a312d857c…`), và `lineage_verified: true` (raw records khớp raw response). Về gate: `data/quality/repaired_quality_report.json` pass 12/12, `data/quality/repaired_freshness_report.json` là FRESH 4.2%, 24 dòng với 24 `paper_id`. Về metric: `data/results/repaired_metrics.json` có hit rate 1.000, token F1 1.000, judge 1.000 và 5.000, tức phục hồi 100% ở cả 4 metric trong `data/reports/corruption_report.md` §1. Metric tốt một mình chưa đủ, vì test set chỉ phủ 10 bài; fingerprint mới cho thấy cả 24 bài đã về đúng như cũ.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | --: | --: | --: | --- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | Chỉ giảm vì một lỗi: drop latest làm mất bài của `eval_001` và `eval_002`. Các câu còn lại vẫn tìm đúng bài vì câu hỏi có tiêu đề trong nháy đơn và tiêu đề của các bài đó không bị đụng tới. |
| `mean_token_f1` | 1.000 | 0.745 | 1.000 | Metric nhạy nhất: bắt cả lỗi nội dung mà hit rate bỏ qua, như noise (`eval_005` còn 0.82, `eval_009` còn 0.89) và ngày bị lùi (`eval_007` về 0). |
| `judge_accuracy` | 1.000 | 0.800 | 1.000 | Chỉ 2 câu bị chấm sai (`eval_002`, `eval_007`). Judge khá dễ dãi: hai câu summary lẫn ký hiệu rác vẫn được chấm đúng, và `eval_001` lấy sai bài nguồn cũng được chấm đúng. |
| `mean_judge_score` | 5.000 | 4.200 | 5.000 | 8 câu 5 điểm, 2 câu 1 điểm. Ở corrupted, 5 câu lấy verdict từ `judge_cache.json`, 5 câu khớp nguyên văn, không câu nào dùng fallback, nên điểm này đúng là của LLM judge chứ không phải heuristic. |
| Quality checks | 12/12 pass | 7/12 pass | 12/12 pass | 5 check fail, mỗi check ứng với đúng một kịch bản, không check nào fail oan. `row_count` vẫn pass với 22 dòng, đúng như lý do tôi thêm `source_papers_present`. |
| Freshness status | FRESH (4.2%) | STALE (31.8%) | FRESH (4.2%) | Corrupted lên 7/22 dòng stale do lỗi lùi ngày. Baseline đã có sẵn 1/24 bài stale (181 ngày, vừa quá ngưỡng 180), nên con số này sẽ tự tăng dần theo ngày chạy dù dữ liệu không đổi. |

### Kết luận từ số liệu

1. **Data corruption → tín hiệu → metric.** Lỗi `stale_date` lùi ngày 7 bài đi 365 ngày → freshness từ 4.2% lên 31.8%, STALE (không check GX nào bắt được lỗi này, vì ngày vẫn đúng định dạng) → `eval_007` trả `2025-06-03` thay vì `2026-06-03`, token F1 từ 1.00 về 0.00 và judge chuyển sang sai. Song song, `drop_latest_records` bỏ 5 bài → `source_papers_present` fail (19/24) → `eval_001` và `eval_002` mất hit, hit rate từ 1.000 xuống 0.800.
2. **Repair → tín hiệu phục hồi → metric phục hồi.** Dựng lại từ `data/raw/crossref_records.json` bằng đúng quy tắc cleaning → gate 12/12, freshness FRESH 4.2%, fingerprint trùng baseline ở cả hai lần repair → cả 4 metric về đúng baseline (hit 1.000, token F1 1.000, judge 1.000 và 5.000), mức phục hồi 100%.

**Corruption nào ảnh hưởng rõ nhất và vì sao?**

Drop latest records. Đây là lỗi duy nhất làm giảm hit rate: mất hit ở 2 câu, token F1 của 2 câu đó giảm trung bình 0.63, và 1 câu bị judge chấm sai (`corruption_report.md` §6). Các lỗi khác chỉ làm sai một trường trong bài vẫn còn đó, còn drop làm bài biến mất hẳn, nên hệ thống buộc phải trả lời bằng một bài khác. Nó cũng là lỗi nguy hiểm nhất, vì ở `eval_001` câu trả lời sai nguồn vẫn được chấm đúng.

**Kết quả nào khác với kỳ vọng ban đầu?**

- Có lỗi thật mà benchmark không thấy. Truncate title (3 dòng) không trúng bài nào trong test set nên không metric nào đổi, chỉ `title_min_length` bắt được. Blank summary trúng bài của `eval_008`, nhưng đó là câu hỏi categories nên câu trả lời không đổi. Tôi kiểm lại bằng bảng §5 của `corruption_report.md` (cột "Lỗi trên paper"): test set 10 câu chỉ thấy lỗi khi lỗi rơi đúng vào trường mà câu hỏi dùng.
- LLM judge dễ dãi hơn tôi nghĩ. Trong `data/results/corrupted_metrics.json`, nhóm câu `summary` có hit rate 0.6667 nhưng judge accuracy vẫn 1.0: câu có ký hiệu rác và câu sai nguồn đều được chấm đúng. Judge không thay được các check dữ liệu.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. **Về data pipeline:** pipeline chạy trên snapshot vẫn "cũ đi" theo lịch dù dữ liệu không đổi, vì `age_days` tính theo ngày chạy. Trên main, baseline chạy ngày 2026-09-25 đã có 1/24 bài stale (181 ngày). Ở bản thử nghiệm, tôi cố định ngày chạy bằng biến `RUN_DATE` để chạy lại vẫn ra cùng báo cáo. Môi trường cũng là một phần của khả năng chạy lại: trên máy Windows có Application Control, một DLL trong wheel scikit-learn bị chặn khi import; tôi pin một phiên bản đã biết chạy được trong venv thay vì tắt tính năng bảo mật đó.
2. **Về data quality/observability:** check theo dòng không nhìn thấy dòng đã mất, nên cần một check so với nguồn (`source_papers_present`). Mỗi loại lỗi cần một detector riêng, và cần test chứng minh detector đó bắt đúng lỗi của nó, vì chính báo cáo của gate cũng có thể sai im lặng (mục 6).
3. **Về ảnh hưởng của data đến RAG agent:** silent failure là có thật. Pipeline chạy không báo lỗi gì, metric câu trả lời vẫn có thể xanh trong khi dữ liệu đã sai: `eval_001` lấy sai bài nguồn mà judge vẫn cho 5/5. Vì vậy gate phải đứng trước vector store, và retrieval phải được đo riêng bằng `ground_truth_doc_ids` chứ không chỉ nhìn chất lượng câu trả lời.

### Nếu có thêm thời gian

Tôi sẽ cố định ngày chạy trên main, ví dụ thêm một biến kiểu `RUN_DATE` vào `Settings` (mặc định vẫn là ngày hiện tại), vì hiện `phase1` và `corruption_flow` đều dùng `now_utc()`. Lý do: theo `age_days` trong `data/clean/papers_clean.json`, bài cũ thứ 7 xuất bản ngày 2026-06-01 (116 ngày), nên từ khoảng 2026-11-29 baseline sẽ có 7/24 bài stale, vượt 25%, và tự chuyển STALE dù không có gì hỏng. Cách đo: chạy `phase1` ở hai ngày khác nhau với cùng `RUN_DATE`, `freshness_report.json` phải cho cùng `stale_ratio`; không có `RUN_DATE` thì con số này có thể trôi theo ngày chạy.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Hoàng Quốc Việt
**Ngày xác nhận:** 2026-09-25
