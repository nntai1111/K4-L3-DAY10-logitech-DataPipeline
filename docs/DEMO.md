# Kịch bản demo (5 đến 7 phút)

Mục tiêu: cho lớp thấy ba điều trong vài phút.

1. Trợ lý chỉ trả lời từ kho đã qua trạm kiểm soát dữ liệu (quality gate) và chỉ ra nguồn cho từng ý.
2. Dữ liệu bẩn làm trợ lý trả lời sai một cách tự tin, không báo lỗi gì; chỉ trạm kiểm soát nhận ra.
3. Dữ liệu mới từ Internet cũng phải qua đúng trạm đó thì trợ lý mới được dùng.

App làm gì và vì sao: xem mục 6 và 7 của [README](../README.md).

## Chuẩn bị (trước giờ trình bày)

1. Đã chạy `python script/run_phase1.py` rồi `python script/run_corruption_flow.py`; app chỉ đọc kết quả của hai script này. Nếu chạy lại ngay trước buổi demo, đặt `RUN_DATE=2026-09-25` để số liệu ở tab Quan sát dữ liệu khớp báo cáo nhóm. Bản thân app không đọc `RUN_DATE`, và kho Live luôn tính theo ngày thật.
2. `.env` có LLM thật (`LLM_PROVIDER=gemini`, `LLM_MODEL`, `GOOGLE_API_KEY`), tùy chọn thêm `CROSSREF_MAILTO`. Mỗi câu hỏi cho agent tốn ít nhất hai lượt gọi LLM, tab So sánh hai kho tốn gấp đôi, nút agent ở tab Silent failure gấp ba; cả kịch bản cỡ ba mươi lượt, nên kiểm tra quota của key trước.
3. Bật internet: cả Gemini lẫn Crossref đều cần mạng.
4. Chạy `streamlit run app/streamlit_app.py` và mở trang trước vài phút. Lần tải đầu chậm vì phải nạp mô hình embedding MiniLM, ChromaDB của ba kho và chọn câu hỏi demo cho tab Silent failure; sau đó đã được cache.
5. Nhìn thanh bên: phải có dòng "Agent LLM: gemini / ...". Nếu thấy "LLM chưa sẵn sàng" thì `.env` chưa đúng.
6. Thanh bên chọn **Live**, bấm **Đưa Live về snapshot**: ô "Kho Live" trên header về 24 bài, để bước 3 thật sự có bài mới. Chọn lại **Repaired**, bấm **Xóa hội thoại**.
7. Tùy chọn: thống kê gate live cộng dồn mọi lần nạp đã ghi trong `data/live/ingest_log/`, kể cả trước buổi demo, và nút reset không xóa nhật ký. Muốn bước 8 chỉ hiện các lần nạp của buổi demo thì chuyển thư mục đó ra chỗ khác trước khi bắt đầu.

Lưu ý khi bấm: nút câu hỏi ví dụ chỉ hiện khi khung chat trống. Sau câu đầu tiên, gõ câu tiếp theo vào ô chat, hoặc bấm **Xóa hội thoại** để các nút hiện lại.

## Thứ tự trình bày

### 1. Trợ lý nghiên cứu trên kho Repaired (1 phút)

- Bấm nút ví dụ: `Kien Duong đã viết những bài nào, xuất bản khi nào?`
- Chỉ vào: dòng bước dưới câu trả lời ghi "lọc theo tác giả" với tham số Kien Duong, còn khung Nguồn gắn nhãn "lọc METADATA" thay cho điểm cosine, vì bài được chọn theo tên tác giả chứ không đoán theo độ giống nghĩa (nếu agent gọi thêm tìm theo nghĩa và gặp lại cùng bài, nhãn chuyển thành điểm cosine).
- Gõ: `Những bài nào về đánh giá retrieval ra sau tháng 6/2026?`
- Chỉ vào: bước "lọc theo ngày" kèm mốc ngày và chủ đề agent tự điền; bài trong khoảng ngày được xếp theo độ liên quan nên vẫn có điểm cosine, và mỗi ý trong câu trả lời có số trích dẫn trỏ tới đúng DOI.

### 2. Câu hỏi ngoài phạm vi (30 giây)

- Gõ: `iPhone 18 có bao nhiêu màu?`
- Chỉ vào: thẻ "Ngoài phạm vi kho bài báo" ghi agent đã tìm gì, cosine cao nhất bao nhiêu và kho có 24 bài về những chủ đề nào, còn ở khung Nguồn mọi bài đều mờ với nhãn "đã đọc, không trích dẫn".

Thẻ này hiện khi agent tìm xong mà không trích được DOI nào; trợ lý không bịa câu trả lời.

### 3. Nạp bài mới vào kho Live (1 phút 30 giây)

- Thanh bên chọn **Live**, bấm **Xóa hội thoại** để hiện các nút ví dụ của kho Live.
- Bấm nút ví dụ: `Cập nhật cho tôi các bài mới về vision-language-action model cho robot`
- Chỉ vào: thẻ "Nạp dữ liệu live" đi qua bảy ô (từ Crossref, sau làm sạch, bị cách ly, gate lô mới, bài mới, gate kho gộp, bài trong kho), kết thúc bằng "ĐÃ NẠP +N", và ô "Kho Live" trên header tăng từ 24.
- Một lần chạy thử ngày 2026-09-25 cho 20 bài lấy về, 0 bị cách ly, +20, kho lên 44 bài. Số thật tùy Crossref trả về hôm đó.
- Gõ câu hỏi tiếp: `Các bài mới về vision-language-action model cho robot đề xuất những gì?`
- Chỉ vào: lần này agent chỉ tìm theo nghĩa, không nạp nữa, và trích DOI của các bài vừa index; trước bước nạp, kho không có bài nào về chủ đề này.

### 4. Lần nạp bị chặn vì dữ liệu cũ (30 giây)

- Gõ: `Add papers on vision-language-action models published since 2023`
- Chỉ vào: thẻ "BỊ CHẶN" với ô "gate lô mới" FAIL và lý do freshness SLA (bao nhiêu phần trăm lô cũ hơn 180 ngày, ngưỡng 25%), các ô phía sau là "—", còn số trên header không đổi.
- Nói rõ: Crossref xếp kết quả theo độ liên quan chứ không theo ngày, nên lô "từ 2023" thường có hơn 25% bài cũ và bị chặn. Nếu hôm đó Crossref trả về toàn bài mới thì lô qua, và đó cũng là kết quả đúng của gate.

### 5. Cách ly dòng bẩn (tùy chọn, 30 giây)

- Gõ: `Update me on new papers about quantum error correction`
- Chỉ vào: nếu ô "bị cách ly" lớn hơn 0, mở mục "N bài bị cách ly" để thấy lý do dạng `junk symbols in summary (...)`, tức tóm tắt dính LaTeX rò rỉ bị giữ lại trong khi phần còn lại của lô vẫn qua gate và được index.
- Nói rõ: có dòng bị cách ly hay không tùy Crossref trả về gì hôm đó. Nếu ô này là 0 thì chuyển bước; luật cách ly có test riêng trong `tests/test_live_ingest.py`.

### 6. So sánh hai kho: Repaired và Live (1 phút)

- Mở tab **So sánh hai kho**. Kho A để Repaired, Kho B để Live (mặc định).
- Bấm nút `Update me on vision-language-action models for robots`, rồi bấm **Hỏi cả hai kho**.
- Chỉ vào: bên Repaired, agent tìm rồi nói kho không có bài về chủ đề này vì nó không có công cụ nạp, còn bên Live có thẻ nạp và câu trả lời trích DOI các bài vision-language-action.
- Bước 3 đã nạp chủ đề này, nên thẻ bên Live có thể chỉ thêm vài bài hoặc hiện "KHÔNG CÓ BÀI MỚI"; nó vẫn trả lời từ các bài đã có.

### 7. Silent failure (1 phút)

- Mở tab **Silent failure**, giữ "Theo kịch bản lỗi", chọn **Ngày bị làm cũ**.
- Chỉ vào: dòng "Đáp án chuẩn" rồi ba thẻ, trong đó Baseline và Repaired khớp đáp án còn Corrupted trả lời lệch một năm với giọng vẫn chắc chắn, các từ sai được đánh dấu, và dòng chú thích bên dưới ghi rằng không kho nào báo lỗi.
- Chọn **Chèn ký tự rác**: thẻ Corrupted mang nguyên ký tự rác ra câu trả lời cho người dùng.
- Tùy chọn (tốn 3 lượt LLM trở lên): bấm **Hỏi agent trên cả ba kho** để thấy agent trên kho bẩn cũng trả lời tự tin, các từ khác với kho sạch được đánh dấu.

### 8. Quan sát dữ liệu (1 phút)

- Mở tab **Quan sát dữ liệu**.
- Chỉ vào: ba thẻ trạng thái (Corrupted GATE FAIL, hit rate và token F1 từ 1.00 xuống 0.80, Repaired về lại 1.00), bảng Quality gate với 4 expectation FAIL và freshness STALE 13/24 dòng ở cột Corrupted, cột "Ai phát hiện" của bảng sáu kịch bản (chỉ `drop_latest_records` là không expectation nào bắt được), và dải cuối ghi bảng sau repair trùng baseline theo sha256.
- Cuộn xuống "Quality gate trên dữ liệu live". Chỉ vào: sáu ô số (lần nạp, qua gate, bị chặn, bài lấy về, bị cách ly, bài thêm vào kho), hai biểu đồ lý do (lần chặn ở bước 4 hiện là "Freshness SLA (dữ liệu cũ)") và bảng nhật ký của đúng các lần vừa chạy.

Số liệu ở bước 8 là của lần chạy chính thức với `RUN_DATE=2026-09-25`.

## Nếu có sự cố

- **Không có mạng, hoặc Crossref không trả lời.** Lần nạp hiện "BỊ CHẶN" với lý do "Crossref could not be reached", kho Live giữ nguyên, không bao giờ lấy snapshot thế vào. Mất mạng hẳn thì Gemini cũng không gọi được: trợ lý chuyển sang trả lời trích xuất, còn ba thẻ so sánh ở tab Silent failure và toàn bộ tab Quan sát dữ liệu vẫn chạy vì chỉ dùng file và index trên máy.
- **Gemini hết quota (429) hoặc lỗi nhà cung cấp.** Tab Trợ lý hiện dải cảnh báo "LLM lỗi, đã chuyển sang chế độ trích xuất" kèm mã lỗi, câu trả lời lấy từ bài gần nhất, và dòng bên dưới ghi "trích xuất, không LLM". Ở tab So sánh hai kho và nút agent của tab Silent failure, cột nào lỗi thì hiện "LLM lỗi". Đây là lỗi gọi LLM, không phải agent từ chối trả lời. Đổi key hoặc model trong `.env` thì phải khởi động lại app.
- **Thẻ nạp hiện "KHÔNG CÓ BÀI MỚI".** Lô mới qua gate nhưng mọi bài đã có trong kho Live, thường vì kho còn bài từ lần chạy trước (kho Live lưu trên đĩa, tắt app không mất). Bấm **Đưa Live về snapshot** ở thanh bên rồi hỏi lại.
- **Lần tải đầu chậm.** Các dòng chờ "Đang nạp ChromaDB và mô hình embedding..." và "Đang chọn câu hỏi demo cho từng kịch bản..." chỉ chạy một lần mỗi lần khởi động app, nên mở trang trước giờ demo. Nút **Đưa Live về snapshot** cũng mất vài giây vì phải nhúng lại 24 bài.
- **Nút câu hỏi ví dụ biến mất.** Chúng chỉ hiện khi khung chat trống; bấm **Xóa hội thoại** hoặc gõ câu hỏi vào ô chat.

## Vì sao agent không tìm web trực tiếp

Agent không có công cụ tìm web. Đường duy nhất để dữ liệu bên ngoài tới được câu trả lời là `ingest_new_papers`, và công cụ này bắt dữ liệu đi qua đúng các bước của pipeline: làm sạch, cách ly dòng bẩn, bộ Great Expectations và freshness SLA, hai lần, trên lô mới và trên kho gộp. Nếu agent đọc web thẳng, một tóm tắt dính LaTeX rò rỉ, một bài từ nhiều năm trước hay một bản trùng sẽ đi thẳng vào câu trả lời mà không ai kiểm, và câu trả lời vẫn trôi chảy như ở tab Silent failure. Dữ liệu mới phải qua cùng một cổng trước khi trợ lý được dùng; đó là điểm chính của bài lab.
