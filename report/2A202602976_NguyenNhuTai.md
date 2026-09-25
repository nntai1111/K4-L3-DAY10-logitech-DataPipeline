# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Như Tài |
| MSSV | 2A202602976 |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | `logitech` |
| GitHub | `nntai1111` |
| Email | taibeo161023@gmail.com |
| Vai trò chính | Trưởng nhóm (team lead); Data Ingestion & Cleaning owner |
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

Ghi chú về lịch sử commit: code của `crossref.py` và `cleaning.py` trên `main` là bản tích hợp, được đưa lên trong commit `b918ef7` của Long. Commit của tôi là `d0474ec` ("demo"), chứa bản tôi tự làm. Khi merge (`99affeb`), nhóm giữ bản tích hợp nên nội dung commit đó không vào `main` (xem bảng bên dưới). Theo phân công trong `docs/TEAM.md`, hai module này giao cho tôi; báo cáo này giải thích quy tắc, contract và kết quả của chúng trên `main`.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Trưởng nhóm: tạo repo nộp bài theo bước CP0 trong `README.md`: fork repo gốc của lớp về tài khoản `nntai1111`, đặt tên theo quy ước `K4-L3-DAY10-<TenNhom>-DataPipeline`, mời các thành viên làm collaborator. | Cả nhóm | Repo nộp bài là https://github.com/nntai1111/K4-L3-DAY10-logitech-DataPipeline. Commit `b918ef7` của Long và PR #1 của Việt đều nằm trên `main` của repo này. |
| Tự làm một bản pipeline đầy đủ trong commit `d0474ec`: parser Crossref, cleaning, luồng corruption có repair dựng lại từ `data/raw/crossref_records.json` qua `build_clean_dataframe`, kèm artifact của lần chạy đó. | Cả nhóm, lúc so sánh và chọn bản để ghép | Nhóm giữ bản tích hợp (merge `99affeb`, "keep integrated pipeline over demo commit"), nên code của bản này không nằm trên `main`. Cách repair của bản này (dựng lại từ raw, không vá dữ liệu hỏng) trùng với cách bản trên `main` dùng (mục 5). Đem bản này so với bản trên `main` cũng cho tôi thấy lỗi ở mục 6. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Parse payload Crossref (bỏ JATS/HTML, chuẩn hoá DOI, tác giả, ngày) | `parse_crossref_payload` | Tái tạo chính xác 24 record của `crossref_records.json` | `tests/test_crossref.py::test_parser_reproduces_committed_records` |
| Gọi API có retry/backoff, fallback snapshot | `fetch_source_records`, `_request_crossref` | 429/5xx được thử lại tối đa 4 lần; vẫn lỗi, hoặc mất mạng → dùng snapshot, không crash | `tests/test_crossref.py` (retry, fallback, không có snapshot) |
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
- Bỏ bản ghi không có `paper_id`, có title dưới 8 ký tự, summary dưới 30 ký tự, hoặc ngày không parse được theo ISO 8601.
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
- **Kết quả thực tế:** chạy lại ngày 2026-09-25 trên code của `main`: hai file test cho 19 test pass; lệnh CP1 in `Tín hiệu hoàn thành: Clean thành công 24 dòng` (0 dòng bị loại vì lỗi, 0 dòng trùng). Lệnh CP0 ghi lại `data/raw/ingestion_manifest.json`, nên tôi không chạy lại nó trên bản nộp; tín hiệu tương ứng nằm trong manifest của lần chạy nộp: `mode: snapshot`, `valid_records: 24`, `skipped_items: 0`.
- **Artifact/log:** `data/raw/ingestion_manifest.json`, `data/clean/papers_clean.csv`.

## 5. Một quyết định kỹ thuật quan trọng

Repair dựng lại dữ liệu từ raw bằng đúng quy tắc cleaning của baseline, và dùng fingerprint theo nội dung để chứng minh kết quả trùng baseline.

- **Bối cảnh:** sau 6 kịch bản lỗi, dữ liệu hỏng còn 22 dòng với 19 `paper_id` (`data/results/corruption_log.json`). Cần một cách đưa dữ liệu về trạng thái đúng, chạy lại bao nhiêu lần cũng ra cùng kết quả (idempotent), và có bằng chứng là kết quả đó thật sự giống baseline. Phần điều phối repair thuộc CP5 do Long làm (`repair_from_raw` trong `src/pipelines/corruption_flow.py`); phần của tôi là quy tắc cleaning mà repair gọi lại và hàm `dataset_fingerprint` dùng để so sánh.
- **Các phương án đã cân nhắc:**
  1. Vá trực tiếp dataframe hỏng: bỏ dòng trùng, xoá ký hiệu rác, cộng lại 365 ngày. Cách này không lấy lại được thứ đã mất: 5 bài bị drop không còn trong frame, 3 summary đã thành chuỗi rỗng, 3 title chỉ còn 7 ký tự. Muốn sửa ngày thì phải biết dòng nào bị lùi, trong khi một bài có `published` năm 2025 hoàn toàn có thể là bài cũ thật. Mỗi loại lỗi lại cần một đoạn vá riêng.
  2. Chép lại file `data/clean/papers_clean.csv` của pha 1. Nhanh, nhưng coi một file trung gian là nguồn đúng, giữ nguyên `age_days` tính theo ngày chạy pha 1, và không cho biết chạy lại pipeline từ nguồn có ra đúng file đó không.
  3. Đọc lại `data/raw/crossref_records.json` (corruption không đụng tới raw), cho chạy qua đúng `build_clean_dataframe` của baseline, rồi so với baseline bằng fingerprint nội dung.
- **Phương án đã chọn:** phương án 3. Bản tôi tự làm (`d0474ec`) đã repair theo cách này, nhưng chỉ chạy một lần và không so với baseline. Bản trên `main` giữ ý đó và thêm ba thứ: kiểm tra lineage (parse lại `crossref_response.json` phải ra đúng các record trong `crossref_records.json`, `corruption_flow.py:43-44`), chạy cleaning hai lần (`corruption_flow.py:46-47`), và so fingerprint của baseline, hai lần repair và dữ liệu hỏng (`corruption_flow.py:112-129`). `dataset_fingerprint` (`cleaning.py:188-192`) tính SHA-256 trên 10 cột nội dung trong `FINGERPRINT_COLUMNS` sau khi đã sắp xếp các dòng, nên thứ tự dòng không ảnh hưởng.
- **Lý do:** cleaning là hàm tất định: cùng raw và cùng ngày chạy thì ra cùng dataframe (hai lần sắp xếp đều dùng `kind="stable"` và lấy `paper_id` để phân định khi trùng ngày). Idempotent vì vậy đến từ chính cách làm. Fingerprint bỏ `age_days` vì cột này đổi theo ngày chạy: nếu pha 1 chạy hôm nay và repair chạy hôm sau, nội dung giống hệt nhưng mọi dòng lệch `age_days` 1 ngày. So bằng metric thì không đủ, vì test set chỉ phủ 10/24 bài; 3 title bị cắt chẳng hạn không trúng câu hỏi nào. Cái giá phải trả: repair chỉ tốt bằng raw. Nếu bản ghi đã sai hoặc đã mất ngay từ lúc nạp, repair sẽ dựng lại đúng cái sai đó. Vì thế phần ingestion phải giữ raw nguyên byte và ghi SHA-256 vào manifest.
- **Bằng chứng quyết định phù hợp:** trong `data/results/repair_log.json`, `baseline_clean`, `repair_run_1` và `repair_run_2` đều là `a9364c4a312d857c…`, còn `corrupted` là `556b513e476978ad…`; kèm `idempotent: true`, `matches_baseline: true`, `lineage_verified: true`, `rows: 24`. Ở lần chạy nộp, `data/clean/papers_clean_repaired.json` và `.csv` còn giống từng byte với `papers_clean.json` và `.csv` (hai pha chạy cùng ngày nên `age_days` cũng trùng). Test `test_fingerprint_ignores_order_and_age_but_not_content` giữ hai tính chất trên: xáo thứ tự dòng và đặt `age_days = 0` thì fingerprint không đổi, sửa một summary thì fingerprint đổi.

## 6. Một lỗi hoặc blocker đã xử lý

Bản đầu tiên của tôi điền ngày giả cho bản ghi có ngày thiếu hoặc sai, khiến bản ghi lỗi trông như bài mới nhất.

- **Triệu chứng/lỗi nguyên văn:** không có lỗi nguyên văn nào để trích, vì không có exception: code chạy xong bình thường. Triệu chứng nằm trong dữ liệu. Với bản trong commit `d0474ec`, một item Crossref có ngày `[[2026, 13, 40]]` vẫn được giữ, với `published = "2026-13-40"` và `age_days = 0`, nên đứng đầu bảng như bài mới nhất. Một item chỉ có trường `created` (`2025-01-02`) lại nhận `published = "2026-01-01"`.
- **Lệnh hoặc bước tái hiện:** lấy hai file của bản cũ bằng `git show d0474ec:src/ingestion/crossref.py` và `git show d0474ec:src/ingestion/cleaning.py`, rồi cho `parse_crossref_payload` và `build_clean_dataframe` của bản đó chạy với ngày chạy 2026-09-25 trên ba item dựa theo `tests/test_crossref.py::test_parser_skips_invalid_items_and_handles_date_fallbacks` (đổi DOI cho khác nhau để không bị gộp khi dedupe): một item chỉ có `created`, một item có `date-parts` `[[2026, 13, 40]]`, một item không có abstract. Bản cũ giữ cả 3: `published = 2026-13-40` với `age_days = 0`; `published = 2026-01-01` với `age_days = 267`; và một dòng có `summary_chars = 0`. Parser trên `main` với cùng input chỉ giữ 1 item, với `published = 2025-01-02`.
- **Nguyên nhân gốc:** bản của tôi coi "không có ngày hợp lệ" là "cần điền một giá trị", thay vì "bản ghi không hợp lệ". Ở parser, thiếu `published` thì điền `"2026-01-01"` (`d0474ec:src/ingestion/crossref.py:37` và `:101`), và chỉ đọc đúng trường `published`, không thử `created` hay các trường ngày khác. Ở cleaning, ngày không parse được thì lấy luôn ngày chạy (`d0474ec:src/ingestion/cleaning.py:40-41`), rồi kẹp `age_days = max(0, age_days)` (`:44`). Vì `age_days` là đầu vào của freshness SLA, bản ghi có ngày hỏng nhận tuổi nhỏ nhất có thể: nó chỉ kéo tỉ lệ stale xuống, không bao giờ làm freshness báo động. Gate cũng không cứu được: `published_iso_date` chỉ kiểm tra regex `^\d{4}-\d{2}-\d{2}$` (`src/observability/quality.py:22`), và cả `2026-13-40` lẫn `2026-01-01` đều khớp regex này. Summary rỗng thì `summary_min_length` còn bắt được; ngày giả thì không check nào bắt.
- **Cách xử lý:** bản trên `main` (bản nhóm giữ khi merge `99affeb`) làm ngược lại: ngày không đọc được thì bỏ bản ghi và đếm lại, không điền giá trị.
  - Parser thử lần lượt `published → published-online → published-print → issued → created` (`PUBLISHED_DATE_FIELDS`, `crossref.py:27`; `_first_date`, `crossref.py:117-122`). `date-parts` không tạo được ngày thật thì `_date_from_block` trả `None` (`crossref.py:109-112`). Không còn trường ngày nào dùng được thì item bị bỏ (`crossref.py:137-138`) và được đếm vào `skipped_items` trong manifest.
  - Cleaning parse lại bằng `pd.to_datetime(..., errors="coerce", format="ISO8601")` (`cleaning.py:139`) và chỉ giữ dòng có `published.notna()` (`cleaning.py:145`); số dòng bị loại vào `cleaning_stats["dropped_invalid"]`. `age_days` tính từ ngày thật (`cleaning.py:151`) và không bị kẹp về 0.
- **Cách xác minh sau khi sửa:** `tests/test_crossref.py::test_parser_skips_invalid_items_and_handles_date_fallbacks` (item `[[2026, 13, 40]]` bị bỏ, item chỉ có `created` nhận `2025-01-02`) và `tests/test_cleaning.py::test_invalid_rows_are_dropped_and_latest_duplicate_wins` (dòng `published="not-a-date"` bị loại, `dropped_invalid` = 4). Hai file test này chạy lại ngày 2026-09-25 trên code của `main`: 19 test pass. Trên snapshot thật, manifest có `skipped_items: 0` và `data/reports/phase1_report.md` ghi 0 dòng bị loại, nên quy tắc này không làm mất bài nào của bản nộp.
- **Điều học được:** ở tầng cleaning, điền giá trị mặc định cho một trường bắt buộc là tự tạo ra silent failure. Với trường mà observability dựa vào (ở đây là ngày, nguồn của `age_days`), bỏ dòng và đếm số dòng bị bỏ an toàn hơn đoán giá trị. Một check regex về định dạng cũng không thay được việc parse ngày thật.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

1. **Từ Crossref đến vector index.** `fetch_source_records` chọn nguồn: mặc định đọc snapshot `data/raw/crossref_response.json`; chỉ gọi `https://api.crossref.org/works` khi bật `REFRESH_SOURCE=1` hoặc chưa có snapshot, có retry cho 429/5xx và lỗi mạng, hỏng hết thì quay về snapshot. Lần chạy nộp dùng `mode: snapshot` với 24/24 item hợp lệ. Payload được parse thành 24 `PaperRecord` (11 trường) ghi vào `data/raw/crossref_records.json`, kèm manifest có SHA-256 của raw response. `build_clean_dataframe` biến các record đó thành bảng 24 dòng, 16 cột. Hai cột quan trọng nhất cho bước sau là `text_for_embedding` (thứ được embed) và `paper_id` (DOI chữ thường, dùng làm ID ở mọi nơi). `phase1` chạy gate GX và freshness trên chính bảng này; gate fail thì dừng, không index. Gate pass thì `LocalEmbeddingIndex.build` embed `text_for_embedding` bằng `all-MiniLM-L6-v2` và ghi vào collection `papers-baseline` trong `data/chroma/`. Metadata đi kèm là các cột dạng chuỗi do cleaning chuẩn bị sẵn: `published` là chuỗi `YYYY-MM-DD` (`cleaning.py:149`) chứ không phải Timestamp, tác giả và categories dùng cột `authors_joined`, `categories_joined` thay vì cột list. ID của mỗi vector là `paper_id::vị trí` (`index.py:50`).
2. **Evaluation set và ground-truth document IDs.** Mỗi câu trong `data/eval/test_set.json` có `ground_truth` (giá trị đúng của một trường: câu đầu của summary, tác giả, ngày hoặc categories) và `ground_truth_doc_ids` (`paper_id` của bài chứa đáp án). Retrieval được tính là trúng khi một trong 4 ID lấy về (`top_k` = 4) nằm trong `ground_truth_doc_ids` (`metrics.py:168`). Đây là so chuỗi chính xác, nên DOI phải được chuẩn hoá giống nhau ở cả index lẫn test set; nếu không, hit rate sai dù retrieval đúng. Còn `mean_token_f1` và judge so câu trả lời với `ground_truth`. Tách hai cách đo giúp thấy lỗi theo cả hai chiều: ở trạng thái corrupted, `eval_007` vẫn trúng đúng bài (hit = true) nhưng trả `2025-06-03` thay vì `2026-06-03` vì ngày của bài bị lùi, token F1 = 0; ngược lại, `eval_001` mất hit vì bài đúng đã bị drop, nhưng judge vẫn chấm đúng.
3. **Quality checks khác freshness monitoring ở đâu.** Quality check (GX, 12 expectation) kiểm tra các luật cố định trên dòng hoặc cả bảng. Nhiều luật trong đó chính là quy tắc cleaning được kiểm lại: `quality.py` import `MIN_TITLE_CHARS`, `MIN_SUMMARY_CHARS`, `CLEAN_COLUMNS` từ `cleaning.py` (`quality.py:13`), và `source_papers_present` dựng danh sách `paper_id` cần có bằng cách cho raw chạy lại qua `build_clean_dataframe` (`quality.py:123`). Cleaning lọc dữ liệu xấu lúc nạp; gate kiểm tra lại sau đó, nên bắt được lỗi sinh ra sau cleaning, như 6 kịch bản corruption. Gate fail thì `phase1` không index. Freshness đo theo thời gian: nó đọc cột `age_days` mà cleaning tính theo ngày chạy; dòng quá 180 ngày là stale, hơn 25% dòng stale thì cả tập là STALE. Trong `phase1` freshness chỉ cảnh báo; trong `corruption_flow`, STALE cũng đủ để kích hoạt repair (`corruption_flow.py:97`). Cùng một dữ liệu, kết quả freshness có thể đổi theo ngày chạy, còn quality check thì không. Lỗi `stale_date` cho thấy hai lớp này bù cho nhau: ngày bị lùi vẫn là chuỗi `YYYY-MM-DD` hợp lệ nên cả 12 check GX không check nào bắt, chỉ freshness thấy (7/22 dòng stale).
4. **Vì sao dùng cùng test set cho baseline, corrupted và repaired.** Đây cũng là nguyên tắc tôi dùng khi nghĩ về repair: muốn so sánh thì chỉ để một thứ thay đổi. Ba trạng thái dùng chung `data/eval/test_set.json`, chung `top_k` và chung LLM, nên chênh lệch metric chỉ có thể đến từ dữ liệu. `phase1` sinh test set một lần từ dữ liệu sạch rồi tái sử dụng (`load_or_build_test_set`), còn `corruption_flow` đọc thẳng file đó cho cả corrupted và repaired (`corruption_flow.py:92`, `:134`). Nếu sinh lại test set từ dữ liệu hỏng, ground truth sẽ lấy từ chính dữ liệu đã hỏng nên câu trả lời sai vẫn khớp đáp án, và bài đã bị drop sẽ không còn câu hỏi nào. Nhờ giữ cố định, tôi so được repaired với baseline đến từng câu: cả 10 câu có cùng hit, token F1, điểm judge, và cùng danh sách 4 ID lấy về.
5. **Repair được xem là thành công dựa trên artifact và metric nào.** Tôi xét theo thứ tự từ dữ liệu ra tới metric. (a) Dữ liệu: `data/results/repair_log.json` có fingerprint hai lần repair trùng nhau và trùng baseline (`a9364c4a312d857c…`), `lineage_verified: true`, `rows: 24`; file repaired giống từng byte file baseline. (b) Observability: `data/quality/repaired_quality_report.json` pass 12/12 với `source_papers_present` 24/24; `data/quality/repaired_freshness_report.json` FRESH, 1/24 dòng stale (4.2%). (c) Metric: `data/results/repaired_metrics.json` có hit rate 1.000, token F1 1.000, judge accuracy 1.000, judge score 5.000, mức phục hồi 100% ở cả 4 metric trong `data/reports/corruption_report.md` §1. Tôi đặt (a) lên trước vì metric chỉ nhìn 10 bài của test set, còn fingerprint cho biết cả 24 bài đã về đúng. Dữ liệu repaired cũng phải qua gate lại rồi mới được index (`corruption_flow.py:105-110`).

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | --: | --: | --: | --- |
| `retrieval_hit_rate` | 1.000 | 0.800 | 1.000 | Hai câu mất hit (`eval_001`, `eval_002`) đều do bài bị drop. Repair lấy lại được vì 5 `paper_id` bị mất vẫn còn trong raw; vá trên dataframe hỏng thì không có gì để lấy lại. |
| `mean_token_f1` | 1.000 | 0.745 | 1.000 | Giảm vì các trường do cleaning sinh ra bị sửa (summary lẫn ký hiệu rác, ngày bị lùi) hoặc bài bị mất hẳn. Về lại đúng 1.000 vì `text_for_embedding` và metadata được sinh lại từ raw. |
| `judge_accuracy` | 1.000 | 0.800 | 1.000 | 2 câu sai: `eval_002` (trả tên tác giả của bài khác) và `eval_007` (năm 2025 thay vì 2026). Cả hai bắt nguồn từ dữ liệu, không phải từ model, nên dựng lại dữ liệu là đủ để sửa. |
| `mean_judge_score` | 5.000 | 4.200 | 5.000 | 8 câu 5 điểm, 2 câu 1 điểm. Sau repair cả 10 câu khớp nguyên văn đáp án nên không cần gọi LLM (`exact_match` = 10), giống baseline. |
| Quality checks | 12/12 pass | 7/12 pass | 12/12 pass | 4 trong 5 check fail là quy tắc cleaning được kiểm lại: `paper_id_unique` (dedupe), `summary_min_length` (≥ 30), `title_min_length` (≥ 8), `source_papers_present` (so với raw qua cùng cleaning). Lỗi được tiêm sau cleaning nên gate là nơi bắt; repair chạy lại cleaning nên về 12/12. |
| Freshness status | FRESH (4.2%) | STALE (31.8%) | FRESH (4.2%) | Freshness chỉ đọc cột `age_days` do cleaning tính. Repaired về đúng 1/24 dòng stale vì `age_days` được tính lại từ ngày gốc trong raw, không phải cộng trừ trên dữ liệu hỏng. |

### Kết luận từ số liệu

1. **Data corruption → tín hiệu → metric.** `drop_latest_records` (5 bài) và `duplicate_rows` (3 dòng) phá hai điều cleaning bảo đảm: đủ bài so với raw, và mỗi `paper_id` chỉ một dòng → `source_papers_present` fail (19/24), `paper_id_unique` fail (6 dòng vi phạm), dữ liệu còn 22 dòng / 19 paper → hit rate 1.000 → 0.800 do mất 2 bài của `eval_001` và `eval_002`. Bản trùng không làm đổi metric nào, nhưng chiếm chỗ trong top-k (xem mục cuối).
2. **Repair → tín hiệu phục hồi → metric phục hồi.** Đọc lại `data/raw/crossref_records.json` (lineage khớp `crossref_response.json`) → chạy `build_clean_dataframe` như baseline, hai lần → fingerprint `a9364c4a312d857c…` ở cả hai lần, trùng baseline và khác bản hỏng (`556b513e476978ad…`) → gate 12/12, `source_papers_present` 24/24, freshness FRESH 4.2% → cả 4 metric về đúng baseline, mức phục hồi 100%, và từng câu lấy về đúng 4 ID như baseline.

**Corruption nào ảnh hưởng rõ nhất và vì sao?**

`drop_latest_records`. Drop, blank summary và truncate title đều xoá mất thông tin gốc, nhưng drop nặng nhất vì mất cả dòng, và là lỗi duy nhất làm giảm hit rate (2 câu, `data/reports/corruption_report.md` §6). Nhìn từ phía repair, đây cũng là lỗi cho thấy rõ nhất vì sao phải dựng lại từ raw: dữ liệu hỏng không còn dấu vết gì của 5 bài đó, chỉ raw còn giữ.

**Kết quả nào khác với kỳ vọng ban đầu?**

- Tôi nghĩ `duplicate_rows` vô hại với RAG, vì hai câu dính lỗi này (`eval_003`, `eval_004`) không đổi kết quả. Nhưng trong `data/results/corrupted_answers.json`, ở `eval_001`, `eval_002` và `eval_007`, một bài bị nhân đôi chiếm 2 trong 4 vị trí top-k (ví dụ `eval_001` lấy về `10.1145/3637528.3671824` hai lần), nên 4 kết quả lấy về chỉ có 3 bài khác nhau. Metric không phạt chuyện này, nhưng nó cho thấy vì sao cleaning phải dedupe theo `paper_id` trước khi index: `index.py:50` dùng `paper_id::vị trí` làm ID nên Chroma nhận cả bản trùng mà không báo lỗi.
- Tôi tưởng trạng thái corrupted sẽ có 1 + 7 = 8 dòng stale (1 bài stale sẵn cộng 7 bài bị lùi ngày), nhưng báo cáo ghi 7. Đối chiếu `stale_paper_ids` trong `data/quality/freshness_report.json` với step 5 của `data/results/corruption_log.json` thì thấy bài stale sẵn `10.1145/3637528.3671805` (181 ngày) cũng nằm trong 7 bài bị lùi, nên số dòng stale chỉ tăng thêm 6.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. **Về data pipeline:** snapshot sạch quá thì không thử được parser. Cả 24 item trong `crossref_response.json` đều có DOI chữ thường, `date-parts` đủ năm, tháng, ngày, và abstract chỉ gồm một thẻ `<jats:p>`. Vì vậy bản của tôi trong `d0474ec` vẫn ghi ra `crossref_records.json` giống bản trước đó về nội dung (chỉ khác ký tự xuống dòng; `git diff --ignore-cr-at-eol 77a0fda d0474ec -- data/raw/crossref_records.json` rỗng), dù nó còn nhiều lỗi: abstract nhiều đoạn bị dính chữ (`AbstractWe study H2O.Second para.`), DOI giữ tiền tố `https://doi.org/` và chữ hoa, `&amp;` không được decode, và ngày giả ở mục 6. Chỉ các payload bẩn viết tay trong `tests/test_crossref.py` mới làm lộ ra khác biệt.
2. **Về data quality/observability:** cleaning và gate phải dùng chung một định nghĩa. Trên `main`, gate lấy ngưỡng từ `cleaning.py` và `source_papers_present` chạy lại chính `build_clean_dataframe`, nên hai bên không thể lệch nhau. Mặt trái là nếu cleaning loại nhầm một bản ghi thì danh sách "cần có" của gate cũng mất bản ghi đó, và gate vẫn báo đủ. Khi ấy dấu vết duy nhất là các con số đếm (`skipped_items` trong manifest, `dropped_invalid` trong `cleaning_stats`), nên phải đọc chúng chứ không chỉ nhìn gate xanh.
3. **Về ảnh hưởng của data đến RAG agent:** lỗi ở tầng dữ liệu đi thẳng vào câu trả lời mà không sinh exception nào. Ngày bị lùi 365 ngày làm `eval_007` trả `2025-06-03`; bài bị drop làm `eval_002` trả tên tác giả của một bài khác. Phần trả lời vẫn làm đúng việc của nó, tức là trích từ dữ liệu được đưa vào, nên cách sửa là dựng lại dữ liệu đúng từ raw chứ không phải chỉnh model hay prompt.

### Nếu có thêm thời gian

Tôi sẽ ghi lại bản ghi nào bị loại và vì sao, thay vì chỉ đếm. Hiện `parse_crossref_payload` bỏ item thiếu DOI, title, abstract hoặc ngày mà không lưu lại gì (`crossref.py:137-138`; manifest chỉ có `skipped_items`), còn `build_clean_dataframe` chỉ ghi `dropped_invalid` và `dropped_duplicates` (`cleaning.py:163-170`). Như điều 2 ở trên, bản ghi bị loại ở hai chỗ này thì gate không thấy được. Cách làm: thêm danh sách bản ghi bị loại kèm lý do (DOI nếu có, nếu không thì vị trí trong payload; lý do như `missing_date`, `summary_too_short`, `older_duplicate`) vào manifest và `cleaning_stats`, in ra trong `phase1_report.md`, và cảnh báo khi tỉ lệ bị loại vượt một ngưỡng, ví dụ 10% số item. Cách đo: một test đưa vào payload có sẵn vài item lỗi phải thấy đúng các ID và lý do trong manifest; với snapshot hiện tại danh sách phải rỗng (vì `skipped_items: 0` và `dropped_invalid: 0`); khi bật `REFRESH_SOURCE=1` thì biết ngay nguồn live có bao nhiêu item bị loại và vì sao.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Như Tài
**Ngày xác nhận:** 2026-09-25
