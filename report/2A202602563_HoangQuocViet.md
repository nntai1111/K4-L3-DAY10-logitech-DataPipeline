# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Họ và tên       | Hoàng Quốc Việt |
| MSSV               | 2A202602563 |
| Khóa/Lớp         | K4 |
| Tên nhóm         | logitech |
| Vai trò chính    | Implementation & integration owner |
| Repository         | https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao  | Trạng thái                                 |
| ------------------ | --------------------- | ---------------- | ----------------- | -------------------------------------------- |
| Raw ingestion | `src/ingestion/crossref.py`: `parse_crossref_payload`, `fetch_source_records_with_mode`, `_fetch_live_payload`, `load_raw_records` | Crossref `/works` hoặc snapshot `data/raw/crossref_response.json` | `data/raw/crossref_records.json`, `list[PaperRecord]` | Hoàn thành |
| Cleaning và data model | `src/ingestion/cleaning.py`: `build_clean_dataframe`, `refresh_derived_columns`, `build_text_for_embedding` | `list[PaperRecord]`, `run_date` | `data/clean/papers_clean.csv`, `.json` (16 cột theo `CLEAN_COLUMNS`) | Hoàn thành |
| Quality gate và freshness | `src/observability/quality.py`: `run_data_quality_checks`, `build_freshness_report` | DataFrame, tên báo cáo | `data/quality/<tên>_quality_report.json`, báo cáo freshness | Hoàn thành |
| Evaluation set | `src/evaluation/testset.py`: `build_test_set`, `load_or_create_test_set` | Bảng sạch | `data/eval/test_set.json` (10 câu) | Hoàn thành |
| Corruption | `src/ingestion/corruption.py`: `corrupt_clean_dataframe` | Bảng sạch, seed 42 | Bảng bẩn, `data/results/corruption_log.json` | Hoàn thành |
| Reporting | `src/observability/reporting.py`: `generate_phase1_report`, `generate_corruption_report` | Metrics, quality, answers, corruption log, repair | `data/reports/phase1_report.md`, `corruption_report.md` | Hoàn thành |
| Orchestration | `src/pipelines/phase1.py`, `corruption_flow.py`, `common.py` | `.env`, artifact pha 1 | `run_context.json`, `repair_idempotency.json`, metrics 3 trạng thái | Hoàn thành |
| B1 Dashboard | `app/streamlit_app.py`, `app/research.py`, `app/data.py`, `app/ui/` | Artifact trong `data/`, 3 collection ChromaDB | Trang Streamlit ba tab: trợ lý nghiên cứu, "Silent failure", quan sát dữ liệu | Hoàn thành |
| B2 Auto-repair | `src/pipelines/corruption_flow.py` | `gate_passed` của batch bẩn | Repair từ raw, `auto_triggered` trong `repair_idempotency.json` | Hoàn thành |
| B3 Pytest | `tests/`, `script/run_tests.sh` | Snapshot raw copy sang thư mục tạm | Kết quả pytest | Hoàn thành: 252 test pass trong 54.47 giây, coverage `src/` 99% |

Phần việc của tôi là đầu vào trực tiếp cho hai thành viên còn lại: Nguyễn Như Tài review, merge và tái hiện từ clean clone; Lò Văn Long chạy lại trên máy thứ hai, chạy corruption flow hai lần để đối chiếu sha256, và review phần quality gate cùng phân tích corruption.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                         | Thành viên/module được hỗ trợ | Kết quả                    |
| ------------------------------------ | ------------------------------------ | ---------------------------- |
| Sửa `persist_path` trong manifest embedding | `src/retrieval/index.py` (code starter), giao diện `app/` | Manifest lưu `data/chroma` tương đối, `LocalEmbeddingIndex.load` đọc được trên máy khác |
| Thêm `RUN_DATE` và đường dẫn `run_context` | `src/core/config.py` | Pha 2 đọc lại đúng `run_date` của pha 1 |
| Ghim scikit-learn 1.7.2 trong `.venv` của máy tôi, không sửa `uv.lock` | Môi trường của nhóm | Pipeline chạy trên máy có Windows Application Control; lockfile dùng chung giữ nguyên |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao       | Cách xác minh         |
| --------------------------- | ----------------------------- | ------------------------- | ----------------------- |
| Parse snapshot, fallback offline | `crossref.py` | 24 item → 24 record | `data/raw/crossref_records.json`; `phase1_report.md` ghi chế độ `snapshot` |
| Làm sạch tất định theo `run_date` | `cleaning.py` | 24 dòng, 0 dòng trùng, `summary` không còn thẻ JATS | `data/clean/papers_clean.json`; `run_context.json` ghi `run_date` 2026-09-25 |
| Quality gate GX 1.x và freshness | `quality.py` | Baseline 8/8 PASS, 1/24 dòng quá hạn; corrupted 4/8 PASS, 13/24 | `data/quality/baseline_quality_report.json`, `corrupted_quality_report.json` |
| Test set 10 câu khớp `qa.py` | `testset.py` | Baseline hit rate 1.000, token F1 1.000 | `data/results/baseline_metrics.json` |
| 6 kịch bản corruption, seed 42 | `corruption.py` | 24 dòng vào, 24 dòng ra; hit rate và F1 xuống 0.800 | `data/results/corruption_log.json`, `corrupted_metrics.json` |
| Repair idempotent, tự kích hoạt | `corruption_flow.py`, `common.py` | Hit rate và F1 về 1.000; sha256 trùng baseline; `auto_triggered: true` | `data/results/repaired_metrics.json`, `repair_idempotency.json` |
| Hai báo cáo Markdown | `reporting.py` | Bảng 3 trạng thái, bảng expectation, kịch bản nào bị check nào bắt, từng câu hỏi | `data/reports/phase1_report.md`, `corruption_report.md` |
| Giao diện Streamlit (B1) | `app/` | Trợ lý nghiên cứu trên một collection; tab "Silent failure" đặt cùng một câu hỏi lên ba collection và hiện câu trả lời cạnh nhau; trang quan sát dữ liệu | `streamlit run app/streamlit_app.py` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`data/results/repair_idempotency.json` là bằng chứng repair dựng lại đúng baseline chứ không che lỗi. File ghi nguồn `data/raw/crossref_records.json`, `run_date` 2026-09-25, `auto_triggered: true`, và `baseline_sha256` bằng `repaired_sha256` (`18f784380c172a51b49d6c79254bcb5b7c0a871dd27c92876a256b07134d7d84`), nên `repaired_matches_baseline` là `true`. Trong lần chạy chính thức, corruption flow chạy hai lần; lần hai đọc sha256 của lần một làm `previous_repaired_sha256`, và vì hai giá trị bằng nhau nên `matches_previous_run` là `true`. Lần chạy trên máy thứ hai của Long sẽ kiểm tra điều này còn đúng ngoài máy tôi.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Pipeline cần chứng minh ba điều bằng số liệu: dữ liệu sạch cho agent trả lời đúng; dữ liệu hỏng làm agent trả lời sai mà không báo lỗi (silent failure), và quality gate phát hiện được phần nào; repair từ nguồn gốc đưa hệ thống về đúng trạng thái ban đầu. Muốn so sánh ba trạng thái có ý nghĩa thì mọi thứ trừ dữ liệu phải cố định: cùng test set, cùng `run_date`, cùng cấu hình index, và corruption phải tái hiện được.

### Cách triển khai

- **Nguồn dữ liệu.** Snapshot `data/raw/crossref_response.json` là nguồn sự thật. Chế độ live chỉ bật khi `REFRESH_SOURCE=1`, và chỉ ghi đè snapshot khi lần gọi thành công, nên một lần API trả 429 không thể làm mất dữ liệu đang có. Retry chỉ áp dụng cho mã tạm thời (429, 5xx), chờ theo `Retry-After` nếu server gửi.
- **Làm sạch tất định.** `build_clean_dataframe` là hàm thuần của (raw records, `run_date`): không đọc đồng hồ, sắp xếp cố định theo `published` giảm dần rồi `paper_id`, và các cột dẫn xuất (`summary_chars`, `text_for_embedding`) luôn tính lại từ cột gốc. Đây là điều kiện để repair ra đúng từng byte của baseline.
- **Quality gate.** GX 1.x chạy ở ephemeral context trên 5 cột cần kiểm. Bốn expectation bắt buộc theo `docs/Guide.md` tạo 6 lượt kiểm tra; tôi thêm 2 expectation cho hai lỗi mà bộ bắt buộc không thấy: độ dài `title` tối thiểu 10 và regex chuỗi từ 3 ký hiệu liên tiếp trong `summary`. GX không trả kết quả theo thứ tự suite, nên tôi khớp từng kết quả về expectation theo cặp (loại, cột). `success` chỉ là GX; freshness nằm bên cạnh, `gate_passed` kết hợp cả hai. Pha 1 dừng không index khi GX fail, còn freshness fail chỉ cảnh báo, vì snapshot sạch vẫn tự già đi theo lịch.
- **Test set.** 10 bài được chọn rải đều theo ngày xuất bản, luân phiên 4 loại câu hỏi. Câu chữ giữ đúng cụm từ `retrieval/qa.py` dùng để chọn trường trả lời, tiêu đề đặt trong dấu nháy đơn để `qa.py` tra theo tiêu đề, và ground truth ở đúng dạng chuỗi index lưu. Nhờ vậy baseline đạt 1.000 và mọi mức giảm sau đó là do dữ liệu.
- **Corruption.** Thứ tự: bỏ bài mới nhất, xóa summary, chèn nhiễu, cắt tiêu đề, lùi ngày, nhân bản. Sau bước bỏ bài, các `paper_id` còn lại được xáo bằng `random.Random(42)` rồi cấp lần lượt cho từng kịch bản, nên bốn kịch bản sửa trường không chạm cùng một dòng và một câu trả lời sai truy được về một kịch bản chính. Nhiễu chèn sau mỗi 3 từ tính từ đầu `summary`, để nằm trong câu đầu là câu `qa.py` dùng làm câu trả lời. `stale_date` sửa 8 dòng vì cần hơn 25% của 24 dòng (ít nhất 7) để SLA fail. Bỏ 4 và nhân bản 4 giữ số dòng ở 24.
- **Repair và idempotency.** Repair đọc lại raw records bằng `load_raw_records`, chạy lại `build_clean_dataframe` với `run_date` đọc từ `run_context.json`, xóa và tạo lại collection `papers-repaired`. `table_sha256` băm JSON của 16 cột hợp đồng theo đúng thứ tự, rồi so với sha256 baseline và sha256 của lần repair trước.
- **Báo cáo.** `generate_corruption_report` đọc kết quả gate thật để ghi kịch bản nào "đã bắt" hay "KHÔNG bắt", không giả định check đã chạy đúng, và đếm số verdict do LLM chấm so với heuristic dự phòng để người đọc biết judge có thật sự chạy hay không (lần chạy chính thức: 10 / 0 ở cả ba trạng thái).

### Input, output và contract

| Thành phần                   | Mô tả                                     |
| ------------------------------ | ------------------------------------------- |
| Input                          | `data/raw/crossref_response.json` (Crossref `/works`), `.env` (`LLM_PROVIDER`, tùy chọn `RUN_DATE`, `REFRESH_SOURCE`) |
| Output                         | Bảng 16 cột `CLEAN_COLUMNS`; `data/quality/*.json`; `data/eval/test_set.json`; `data/results/*_metrics.json`, `*_answers.json`, `corruption_log.json`, `run_context.json`, `repair_idempotency.json`; `data/reports/*.md` |
| Module phụ thuộc             | `core/config.py`, `core/utils.py`, `retrieval/index.py`, `retrieval/qa.py`, `evaluation/metrics.py` (code starter) |
| Module sử dụng output        | `retrieval/index.py` đọc `text_for_embedding` và metadata; `evaluation/metrics.py` đọc test set; `app/` đọc toàn bộ artifact |
| Điều kiện lỗi cần xử lý | Crossref trả 429/5xx hoặc mất mạng (fallback snapshot); item thiếu DOI/title/abstract/ngày (bỏ qua); GX fail ở baseline (dừng, không index); bảng repaired vẫn fail GX (dừng); thiếu `run_context.json` khi chạy pha 2 (dừng, nhắc chạy pha 1 trước); LLM không sẵn sàng (judge heuristic dự phòng) |

### Cách xác minh

```bash
python script/run_phase1.py
python script/run_corruption_flow.py
```

- **Kết quả mong đợi:** Pha 1 in GX PASS, hit rate và token F1 1.000. Pha 2 in gate baseline PASS, corrupted FAIL, repaired PASS, và `Repaired == baseline: True`.
- **Kết quả thực tế:** Lần chạy chính thức trên máy tôi (Windows 11, `gemini` / `gemini-3.5-flash-lite`), pha 1 lúc 2026-09-25 08:39 UTC, corruption flow chạy hai lần, lần cuối lúc 08:42 UTC. Baseline 8/8 expectation, hit rate 1.000, token F1 1.000, judge accuracy 1.000, judge score 5.000. Corrupted 4/8 expectation, freshness 13/24, hit rate 0.800, token F1 0.800, judge accuracy 0.800, judge score 4.200. Repaired 8/8, cả bốn chỉ số về như baseline, sha256 trùng baseline và trùng lần chạy trước. Cả 30 verdict judge đều do LLM chấm.
- **Artifact/log:** `data/reports/phase1_report.md`, `data/reports/corruption_report.md`, `data/results/run_context.json`, `data/results/repair_idempotency.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** `age_days` phụ thuộc vào ngày tính. Repair phải cho ra đúng bảng baseline, và freshness SLA của baseline phải so được với của repaired.
- **Các phương án đã cân nhắc:** (1) Tính `age_days` bằng ngày hiện tại bên trong hàm cleaning. (2) Chép `age_days` từ bảng baseline sang bảng repaired. (3) Truyền `run_date` vào hàm cleaning, ghi vào `run_context.json` ở pha 1, và pha 2 đọc lại đúng giá trị đó.
- **Phương án đã chọn:** (3), kèm biến `RUN_DATE=YYYY-MM-DD` để tái hiện một lần chạy cũ.
- **Lý do:** Với (1), nếu pha 2 chạy sang ngày khác pha 1 (qua nửa đêm UTC, hoặc chạy lại hôm sau), mọi `age_days` lệch 1, sha256 khác, và tỷ lệ quá hạn có thể đổi, dù dữ liệu không hỏng gì. Với (2), repair lấy một phần kết quả từ bảng đã xử lý thay vì dựng lại từ nguồn, tức là che lỗi. (3) giữ cleaning là hàm thuần của (raw records, `run_date`), nên cùng đầu vào luôn ra cùng một bảng.
- **Bằng chứng quyết định phù hợp:** `run_context.json` và `repair_idempotency.json` cùng ghi `run_date` 2026-09-25; `baseline_sha256` bằng `repaired_sha256`; freshness baseline và repaired cùng 1/24 dòng quá hạn, tuổi trung vị 110.5 ngày.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `ImportError: DLL load failed while importing _csr_polynomial_expansion: An Application Control policy has blocked this file.`
- **Lệnh hoặc bước tái hiện:** `uv sync` (cài scikit-learn 1.9.0 theo `uv.lock`), rồi `python script/run_phase1.py`. Import `pipelines.phase1` kéo theo `sklearn.preprocessing`, qua sentence-transformers.
- **Nguyên nhân gốc:** Windows Application Control trên máy tôi chặn DLL đã biên dịch của bản build scikit-learn 1.9.0. Package không thiếu và không hỏng; chính sách bảo mật từ chối file DLL cụ thể đó.
- **Cách xử lý:** Ghim bản 1.7.2 riêng trong `.venv`: `uv pip install --python .venv/Scripts/python.exe scikit-learn==1.7.2`. Tôi không sửa `uv.lock`, vì đó là lockfile dùng chung của nhóm và máy khác không có chính sách này, và không tắt Application Control, vì đó là thiết lập bảo mật.
- **Cách xác minh sau khi sửa:** `.venv` có `scikit_learn-1.7.2`; import `pipelines.phase1` thành công; hai script chạy hết trong lần chạy chính thức và ghi báo cáo lúc 2026-09-25 08:39 và 08:42 UTC.
- **Điều học được:** Trên Windows, "DLL load failed" có thể là chính sách hệ thống chứ không phải cài đặt lỗi, nên cài lại package không giải quyết được. Sửa ở môi trường cục bộ và giữ lockfile chung nguyên vẹn. Vì `uv sync` và `uv run` cài lại bản trong lockfile, tôi phải ghim lại sau mỗi lần sync và chạy script bằng `python` trong `.venv` đã kích hoạt.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

1. **Từ Crossref đến vector index.** Response `/works` (snapshot hoặc live) được parse thành `PaperRecord`: bỏ thẻ JATS trong abstract, chuẩn hóa DOI làm `paper_id`, chọn ngày xuất bản theo thứ tự ưu tiên, bỏ item thiếu trường bắt buộc, và lưu `crossref_records.json`. Cleaning chuẩn hóa text, tính `age_days` theo `run_date`, khử trùng lặp, sinh `text_for_embedding` 5 phần. Quality gate chạy trước khi index; GX fail thì dừng. Cuối cùng MiniLM embed `text_for_embedding` và ChromaDB lưu vector cùng metadata (`published`, `authors_joined`, `categories_joined`, `summary`) mà `qa.py` dùng để trích câu trả lời.
2. **Test set và ground-truth document IDs.** Mỗi câu có `ground_truth` (chuỗi đáp án) và `ground_truth_doc_ids` (`paper_id` của bài được hỏi). Retrieval hit đo xem `paper_id` đúng có nằm trong top-4 không; token F1 so câu trả lời với `ground_truth`; judge chấm câu trả lời theo ngữ nghĩa. Hit đo phần tìm kiếm, F1 và judge đo câu trả lời, nên hai nhóm chỉ số có thể lệch nhau, như eval_010 hit ✗ mà F1 1.00.
3. **Quality checks khác freshness.** Quality checks (GX) hỏi "dữ liệu có hỏng về cấu trúc không": null, trùng, độ dài, ký tự rác. Freshness hỏi "dữ liệu có còn mới không": tỷ lệ bài quá 180 ngày. Một bảng hoàn toàn hợp lệ vẫn có thể stale, nên tôi báo freshness tách khỏi `success` của GX. `stale_date` cho thấy sự khác biệt này: không expectation GX nào fail, chỉ freshness bắt được.
4. **Vì sao dùng cùng test set.** Nếu câu hỏi đổi theo dữ liệu, chênh lệch chỉ số không còn quy được về dữ liệu. Tệ hơn, test set sinh từ bảng bẩn sẽ không bao giờ hỏi về bài bị bỏ, nên `drop_latest_records` biến mất khỏi phép đo. `run_context.json` ghi sha256 của test set để kiểm được rằng file không đổi.
5. **Repair thành công dựa trên gì.** Ba điều cùng đúng: bảng repaired qua GX 8/8 và freshness 1/24; sha256 bảng repaired trùng baseline (`repair_idempotency.json`); metrics repaired trùng baseline ở cả bốn chỉ số (`repaired_metrics.json`). Chỉ metrics phục hồi thì chưa đủ, vì một bảng khác baseline vẫn có thể đạt điểm cao trên 10 câu hỏi.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal          | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| ---------------------- | -------: | --------: | -------: | ------------------------- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | Cả 2 câu miss (eval_009, eval_010) nằm trên bài bị `drop_latest_records` bỏ, là kịch bản gate không bắt |
| `mean_token_f1`      | 1.000 | 0.800 | 1.000 | 2 câu F1 0.00: eval_007 (ngày bị lùi) và eval_009 (bài bị bỏ, bài thay thế bị xóa summary) |
| `judge_accuracy`     | 1.000 | 0.800 | 1.000 | LLM judge `gemini-3.5-flash-lite`, 30/30 verdict do LLM chấm. Đánh `correct: false` cho đúng hai câu F1 0.00 (eval_007, eval_009), và vẫn đánh đúng eval_010 dù nguồn sai |
| `mean_judge_score`   | 5.000 | 4.200 | 5.000 | 8 câu 5 điểm, 2 câu 1 điểm; judge trùng kết luận với token F1 ở cả 10 câu corrupted |
| Quality checks         | 8/8 | 4/8 | 8/8 | FAIL ở unique `paper_id`, độ dài `title`, độ dài `summary`, regex `summary`; row count vẫn PASS ở 24 dòng |
| Freshness status       | Fresh, 1/24 | Stale, 13/24 | Fresh, 1/24 | Bài mới nhất lùi từ 2026-07-22 về 2026-06-12 rồi trở lại |

### Kết luận từ số liệu

1. `stale_date` lùi ngày 8 dòng → freshness chuyển sang Stale (13/24 dòng quá hạn) → chỉ eval_007, câu hỏi về ngày, rơi F1 từ 1.00 xuống 0.00 (trả lời `2025-06-09` thay vì `2026-06-09`); eval_004, eval_005, eval_008 cũng nằm trên bài bị lùi ngày nhưng hỏi categories hoặc summary nên vẫn 1.00.
2. Repair đọc lại raw records với cùng `run_date` → GX 8/8 và freshness 1/24 trở lại, sha256 trùng baseline → cả bốn metric về đúng 1.000, 1.000, 1.000, 5.000.

Corruption nào ảnh hưởng rõ nhất và vì sao?

`drop_latest_records`. Nó là nguyên nhân của cả hai lần hit rate giảm và góp vào một lần F1 về 0, và là kịch bản duy nhất không expectation nào bắt: `duplicate_rows` bù đúng 4 dòng nên row count vẫn 24 và PASS, còn không expectation nào nhìn vào ngày mới nhất. Dấu vết duy nhất là `latest_published` trong báo cáo freshness lùi từ 2026-07-22 về 2026-06-12, và freshness vẫn fail chủ yếu vì `stale_date` chứ không vì bài bị bỏ. Trong vận hành thật, lỗi ingestion kiểu này sẽ đi thẳng qua gate.

Kết quả nào khác với kỳ vọng ban đầu?

- Tôi kỳ vọng mọi câu hỏi trên bài bị bỏ đều mất điểm F1, nhưng eval_010 vẫn đạt F1 1.00. Kiểm tra `retrieved_doc_ids` trong `data/results/corrupted_answers.json`: top-1 là bài gần trùng "Advanced Perspectives on Continuous Benchmark Evaluation for Enterprise Retrieval Pipelines" (`...71824`), cùng tác giả "Quang Le, Yen Vu". Câu trả lời đúng nhưng nguồn sai; đây là dạng silent failure thuần nhất. Cả LLM judge cũng chấm 5/5, vì judge chỉ so câu trả lời với đáp án, nên chỉ hit rate lộ ra.
- `blank_summary` không có câu hỏi nào trỏ trực tiếp vào 3 dòng của nó, nên cột "Câu hỏi bị ảnh hưởng" trong `corruption_report.md` để trống. Nhưng eval_009 trả lời chuỗi rỗng vì top-1 thay thế là "Advanced Perspectives on Synthetic Corruption Testing" (`...71819`), một trong 3 dòng bị xóa summary. Cách quy câu hỏi về kịch bản theo ground-truth doc ID bỏ sót tác động gián tiếp này.
- eval_006 đạt cả hit ✓ lẫn F1 1.00 dù tiêu đề bài đúng bị cắt còn "Automat": tra theo tiêu đề thất bại, bài gần trùng `...71822` cùng tác giả lên top-1, bài đúng xuống hạng 3. Hit rate, token F1 và LLM judge (5/5) đều không thấy nguồn đã đổi.
- Sau lần chạy chính thức, đọc lại `data/raw/crossref_records.json` cho thấy một lỗi có sẵn trong snapshot nguồn mà không check nào của tôi bắt: cả 12 bài "Advanced Perspectives on …" có abstract là "An extended empirical study on " cộng abstract của bài gốc cùng tên nhưng mất ký tự đầu, ví dụ "etrieval-Augmented Generation" (`...71813`), "oft-deletions" (`...71815`). Mọi expectation đều PASS vì văn bản vẫn đủ dài và sạch ký hiệu. Chữ cụt còn nằm trong ground truth của eval_005 ("... study on valuating open-domain QA ..."), nên baseline F1 1.00 được đo trên một đáp án đã lỗi. Snapshot được giữ nguyên để không phá lineage; lỗi này được ghi vào mục giới hạn của báo cáo nhóm.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Idempotency của pipeline phụ thuộc vào mọi đầu vào của bước transform, kể cả những thứ trông như môi trường như ngày chạy. Khi `run_date` là tham số và được lưu lại, repair trở thành một phép kiểm bằng hash thay vì một nhận định bằng mắt.
2. Một check chỉ bắt được đúng loại lỗi nó được viết cho. Row count bị qua mặt bởi bỏ 4 cộng nhân bản 4; not-null trên `text_for_embedding` bị qua mặt bởi `summary` rỗng. Mỗi kịch bản cần một check nhắm thẳng vào trường bị hỏng, và kịch bản không có check tương ứng (`drop_latest_records`) sẽ đi qua gate.
3. Dữ liệu hỏng chỉ làm giảm metric khi trường bị hỏng đúng là trường câu hỏi hỏi tới, và corpus có bài gần trùng có thể che lỗi hoàn toàn. Metric cao trên một test set nhỏ không chứng minh dữ liệu sạch; quality gate và metric phải được đọc cùng nhau.

### Nếu có thêm thời gian

Thêm metric "nguồn top-1 là tài liệu đúng" bên cạnh hit rate, vì `qa.py` trả lời từ top-1 còn hit rate chấp nhận tài liệu đúng ở bất kỳ vị trí nào trong top-4. Trên artifact hiện tại, 3 câu corrupted (eval_006, eval_009, eval_010) có top-1 không phải tài liệu đúng, trong khi hit rate chỉ thấy 2 câu và token F1 chỉ thấy 1 trong 3 câu đó. Đo cải thiện: metric mới phải bằng 1.000 ở baseline và repaired, và thấp hơn hit rate ở corrupted.

## 10. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [ ] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Hoàng Quốc Việt
**Ngày xác nhận:** 2026-09-25
