# MỤC LỤC

Báo cáo được tổ chức thành 14 chương, tài liệu tham khảo và các phụ lục kỹ thuật. Sử dụng ngăn Outline của Google Docs hoặc Navigation Pane của Word để truy cập các chương. Số trang cần được cập nhật sau khi dàn trang cuối cùng; không chèn số trang giả định.

DANH MỤC CHƯƠNG: 1. Tổng quan; 2. Cơ sở lý thuyết; 3. Công nghệ; 4. Yêu cầu; 5. Kiến trúc; 6. Tiếp nhận PDF; 7. Công thức; 8. Bố cục, bảng và ảnh; 9. PDF scan mờ; 10. Backend và an toàn; 11. Hiện trạng triển khai; 12. Kiểm thử và đánh giá; 13. Thảo luận, giới hạn; 14. Kết luận. Phụ lục A–E và tài liệu tham khảo.

# DANH MỤC TỪ VIẾT TẮT

PDF — Portable Document Format; DOCX — Office Open XML Word Document; OCR — Optical Character Recognition; OMML — Office Math Markup Language; DPI — Dots Per Inch; bbox — Bounding Box; CER — Character Error Rate; WER — Word Error Rate; API — Application Programming Interface; UI — User Interface; E2E — End-to-End; OOXML — Office Open XML; SHA — Secure Hash Algorithm; CPU/GPU — Central/Graphics Processing Unit.

# LỜI MỞ ĐẦU

Tài liệu toán học phổ biến dưới dạng PDF vì giữ được hình dạng trang in, nhưng khả năng chỉnh sửa và tái sử dụng nội dung còn hạn chế. Khó khăn rõ nhất xuất hiện ở phân số, chỉ số trên/dưới, ma trận, hệ phương trình, bảng biến thiên, hình vẽ lẫn nội dung chia hai cột. Với bản scan, các dấu toán nhỏ và dấu tiếng Việt dễ nhầm lẫn; một hệ thống chuyển đổi đáng tin cậy phải biết cảnh báo chỗ không chắc chắn thay vì âm thầm sinh nội dung sai.

Đồ án nghiên cứu quy trình PDF → Word tập trung vào chất lượng công thức, khả năng chỉnh sửa và bố cục. Hệ thống không thực hiện hỏi đáp nội dung; mọi lựa chọn thuật toán, dữ liệu, API và giao diện phải phục vụ trực tiếp quá trình chuyển đổi. Báo cáo phân biệt rõ thiết kế đề xuất, hạng mục có mã nguồn và kết quả đã được kiểm chứng.

# CHƯƠNG 1. TỔNG QUAN ĐỀ TÀI

## 1.1. Bối cảnh và phát biểu bài toán

Đầu vào là một hoặc nhiều tệp PDF toán học có thể được tạo từ Word/LaTeX, trộn text với ảnh, hoặc là bản quét từng trang. Đầu ra mong muốn là tệp DOCX có đoạn văn và bảng Word, hình ảnh được giữ, công thức nhận dạng được biểu diễn dưới dạng Word Equation (OMML). Không đồng nhất độ giống hình ảnh với độ chính xác ngữ nghĩa: tài liệu có thể trông giống PDF nhưng công thức chỉ là ảnh; cũng có thể hoàn toàn chỉnh sửa được nhưng phân cột và căn lề sai.

## 1.2. Mục tiêu nghiên cứu

Nghiên cứu phân loại nguồn PDF; lựa chọn chiến lược trích xuất text trực tiếp so với OCR; phát hiện và nhận dạng công thức; chuyển LaTeX sang OMML; tái tạo thứ tự đọc và phân cột; xử lý bảng, ảnh và các trường hợp suy giảm chất lượng; xây dựng thử nghiệm có ground truth, tiêu chí định lượng và kiểm tra thị giác. Mỗi mục tiêu cần một bằng chứng nghiệm thu thay vì khẳng định chung 'chính xác'.

## 1.3. Mục tiêu sản phẩm và phạm vi

Sản phẩm mục tiêu có luồng chọn PDF → tạo công việc chuyển đổi → xem trạng thái/cảnh báo → tải DOCX → xem trước và đối chiếu trang. Phạm vi trọng tâm là văn bản tiếng Việt/Anh và công thức toán học in máy; hỗ trợ PDF scan trong điều kiện ảnh đủ thông tin. Việc giải toán, tóm tắt, hội thoại, tìm kiếm ngữ nghĩa hoặc tự động suy diễn lại ký hiệu mất nét không thuộc phạm vi nghiệm thu.

## 1.4. Tiêu chí thành công có thể đo

Một bản chuyển đổi thành công phải tạo DOCX hợp lệ, không rỗng và mở được bằng Word; công thức đã nhận dạng có cấu trúc OMML có thể chỉnh sửa; thứ tự đọc, bảng và ảnh không bị đảo/lẫn trang; mọi thành phần không thể phục hồi phải được thể hiện trong log/cảnh báo hoặc giữ ảnh gốc theo chính sách fallback. Không tự động công bố tỷ lệ thành công nếu chưa có tập mẫu và nhãn tham chiếu.

## 1.5. Phương pháp nghiên cứu

Kết hợp nghiên cứu tài liệu chính thức, đọc mã nguồn dự án, thiết kế và cài đặt thử nghiệm, unit test, kiểm thử E2E, so sánh PDF gốc với DOCX render lại, đánh giá thủ công ký hiệu toán. Thiết kế thử nghiệm so sánh ít nhất hai chế độ: baseline trích xuất/cấu trúc đơn giản và pipeline có phân tích layout, sau đó báo cáo độ chính xác lẫn tài nguyên thực thi.

# CHƯƠNG 2. CƠ SỞ LÝ THUYẾT PDF VÀ WORD

## 2.1. PDF và tầng hiển thị

PDF có thể biểu diễn glyph, đường vector, ảnh raster, thông tin font và phép biến đổi tọa độ để hiển thị trang. PDF không mặc nhiên mang cấu trúc đoạn, bảng, cột hay biểu thức toán giống Word. Một thứ tự ký tự trong content stream không nhất thiết trùng thứ tự đọc. Đây là nguyên nhân không thể đơn thuần đổi phần mở rộng PDF thành DOCX hoặc dùng text extraction để giải bài toán dàn trang.

## 2.2. Text-based PDF, scan PDF và PDF hỗn hợp

Text-based PDF thường có các text span trích xuất được; scan PDF là ảnh của trang; PDF hỗn hợp có thể có OCR text ẩn và ảnh nền. Cần kiểm tra nhiều trang, mật độ ký tự và vùng nội dung thay vì kết luận toàn bộ tài liệu chỉ từ ba trang đầu. Trường hợp có text layer nhưng lỗi mã hóa cũng có thể cần OCR một phần.

## 2.3. Tọa độ và bbox

Mỗi block nội dung có thể được mô tả bằng bounding box (x0, y0, x1, y1) trong hệ tọa độ trang. Khi lưu bbox đã chuẩn hóa về 0–1000 cần quy đổi về kích thước thực của trang; không được giả định mọi trang A4 hoặc mọi trang đứng. Việc đánh giá vị trí phải xét cropbox, page rotation và quy tắc hệ tọa độ từng công cụ.

## 2.4. Văn bản trong DOCX và OOXML

DOCX là gói ZIP chứa các thành phần XML và tài nguyên. WordprocessingML lưu đoạn và bảng dưới các thẻ như w:p, w:r, w:t, w:tbl, trong khi toán học dùng không gian tên m với m:oMath/m:oMathPara. Việc chỉ đếm tệp media không đủ xác định khả năng chỉnh sửa; cần kiểm tra XML thực và mở tệp trong trình xử lý Word.

## 2.5. Office Math, LaTeX và giới hạn tương thích

LaTeX là một dạng biểu diễn văn bản của công thức; OMML là dạng Word dùng để lưu và chỉnh sửa. Không phải mọi macro LaTeX đều có phép ánh xạ tương đương. Trước khi chuyển đổi cần chuẩn hóa lệnh legacy, cặp ngoặc, environment và các ký hiệu ngoại lệ; sau chuyển đổi cần phát hiện công thức bị giữ ở dạng chuỗi nguồn hoặc bị rơi mất.

## 2.6. Bố cục lô-gic và bố cục thị giác

Bố cục lô-gic gồm tiêu đề, đoạn, danh sách, công thức, chú thích, thứ tự đọc; bố cục thị giác gồm vị trí, khổ giấy, lề, khoảng cách, cột và ngắt trang. Hai mục tiêu có thể xung đột: ép đúng từng tọa độ đôi khi làm Word khó sửa. Thiết kế phải định nghĩa mức ưu tiên và ghi nhận trade-off này.

# CHƯƠNG 3. KHẢO SÁT CÔNG NGHỆ

## 3.1. PyMuPDF và pypdf

PyMuPDF hỗ trợ đọc trang, lấy các block/line/span cùng bbox và render vùng ảnh để đối chiếu; pypdf giúp truy cập cấu trúc PDF và trích xuất text ở mức cơ bản. Không dùng độ dài text trích xuất làm bằng chứng duy nhất về chất lượng, bởi ký hiệu toán và các PDF có font lạ thường khó đọc đúng dù extraction thành công về mặt API.

## 3.2. MinerU

MinerU là thành phần phân tích tài liệu được sử dụng trong repository, tạo nội dung có cấu trúc, Markdown, hình ảnh và thông tin khu vực trang. Pipeline phải quản lý sự khác nhau về CLI/định dạng đầu ra giữa các phiên bản, giữ version/config trong báo cáo thực nghiệm. Đầu ra MinerU là nhận dạng có thể sai, cần hậu xử lý và kiểm chứng chứ không mặc định đúng tuyệt đối.

## 3.3. OCR thông thường và OCR công thức

OCR ký tự tổng quát có thể khôi phục dòng văn bản tiếng Việt/Anh nhưng không giải quyết đầy đủ công thức hai chiều, dấu căn, phân số phân tầng, ma trận hoặc quan hệ không gian. Nhận dạng công thức cần mô hình/khối xử lý nhận dạng toán, còn bảng cần phân đoạn hàng/cột/cell. Các bước phải trao đổi thông tin thông qua biểu diễn trung gian có tọa độ và loại block.

## 3.4. Pandoc, python-docx và Microsoft Word

Pandoc chuyển nội dung Markdown có toán sang DOCX; theo manual chính thức, toán trong DOCX được biểu diễn bằng OMML. python-docx hữu ích cho style, footer, table, section nhưng không nên coi nó là trình biên dịch tổng quát LaTeX → Equation. Kiểm tra thành phẩm bằng ZIP/XML kết hợp mở trên Word và render so sánh.

## 3.5. OpenCV/Pillow cho ảnh suy giảm

Tiền xử lý có thể bao gồm đổi gray, deskew, loại nhiễu, local contrast, upscaling có kiểm soát và threshold thích nghi. Không nên áp một công thức tăng sắc nét duy nhất cho tất cả trang: khi chữ đã rõ, sharpen quá mức có thể làm đứt nét, kết dính ký tự hoặc mất dấu chấm, dấu phẩy.

## 3.6. Cơ sở chọn giải pháp

Tiêu chí lựa chọn công nghệ gồm khả năng hỗ trợ ký hiệu toán, OCR tiếng Việt, layout, bảng, khả năng xử lý cục bộ, license phù hợp, độ trễ, tài nguyên phần cứng, mức độ tích hợp và khả năng tái lập. Chọn công nghệ theo bài toán và bằng chứng benchmark trên tập mẫu của nhóm; không suy từ thông tin quảng bá hoặc benchmark ngoài điều kiện thí nghiệm.

# CHƯƠNG 4. PHÂN TÍCH YÊU CẦU

## 4.1. Tác nhân và các kịch bản

Người dùng chọn tài liệu PDF, kiểm tra tên/kích thước và xác nhận chuyển đổi; hệ thống trả mã công việc, tiến trình, kết quả và liên kết tải Word. Người dùng kỹ thuật có thể chọn chế độ OCR, tùy chọn giữ ảnh khi công thức khó, cấu hình khổ giấy và xuất báo cáo chất lượng. Quản trị hệ thống theo dõi lỗi và xóa tài liệu quá hạn.

## 4.2. Yêu cầu chức năng

FR-01 kiểm tra đúng định dạng PDF, giới hạn kích thước/trang; FR-02 trích xuất trang và tự nhận diện text/scan; FR-03 phân đoạn các loại block; FR-04 nhận dạng/chuẩn hóa công thức; FR-05 tái tạo Word Equation; FR-06 giữ thứ tự đọc, bảng, hình và chú thích; FR-07 xuất DOCX nguyên tử; FR-08 theo dõi tiến trình và cảnh báo; FR-09 cho phép tải tệp; FR-10 cung cấp báo cáo kiểm tra chất lượng.

## 4.3. Yêu cầu phi chức năng

NFR-01 không thực thi nội dung tùy ý từ PDF/LaTeX; NFR-02 mỗi tài liệu có thư mục xử lý tách biệt; NFR-03 tính lặp lại của chuyển đổi trên cùng input/config; NFR-04 có timeout/cancel và không giữ lock vô hạn; NFR-05 giới hạn CPU/RAM/dung lượng; NFR-06 dọn dữ liệu tạm; NFR-07 log không rò rỉ nội dung nhạy cảm; NFR-08 có kiểm thử regression với tài liệu đặc trưng.

## 4.4. Ma trận ưu tiên

MVP/P0: upload, parser chạy được, Word tải được, công thức cơ bản thành Equation và báo lỗi rõ. P1: nhiều cột, bảng phức tạp, ảnh/quy tắc fallback và PDF scan khó. P2: tối ưu tốc độ, theo dõi chất lượng từng trang, confidence calibration và benchmark rộng. Các tiêu chí chưa có code được ghi là dự kiến, không trình bày như tính năng đã triển khai.

## 4.5. Giới hạn phạm vi chủ đích

Không đặt mục tiêu giải nghĩa toán học hoặc tự điền số/hàm bị khuất. Với một bản scan không còn thông tin vật lý, thuật toán không thể suy ra duy nhất ký hiệu gốc. Khi khả năng phục hồi thấp, phải ưu tiên giữ ảnh rõ nguồn gốc, đánh dấu cần kiểm tra hoặc yêu cầu bản quét tốt hơn.

# CHƯƠNG 5. KIẾN TRÚC TỔNG THỂ HỆ THỐNG

## 5.1. Pipeline chính

PDF đầu vào → validator → page analyzer → router text/OCR → MinerU extraction → content blocks + bounding boxes → math/table/image normalization → DOCX builder (Pandoc/OMML) → layout postprocessor → OOXML preflight → visual/manual QA → DOCX và báo cáo. Dữ liệu trung gian được giữ theo từng run để xác định nguyên nhân lỗi; các thành phần không liên quan đến chuyển đổi không thuộc pipeline này.

## 5.2. Thiết kế tách lớp

Lớp giao diện chỉ nhận tệp, hiển thị trạng thái và trả link; lớp HTTP adapter kiểm soát kích thước, MIME/magic bytes và phân quyền; lớp application orchestration tạo job và điều phối parser/export; lớp domain thực hiện chuyển đổi; lớp infrastructure cung cấp filesystem, database trạng thái và thực thi subprocess. Dạng module nhỏ giúp kiểm thử mà không cần tải toàn bộ OCR model.

## 5.3. Thiết kế biểu diễn trung gian

Một ContentBlock gồm doc_id, page_index, type, bbox, reading_order, text/latex/table_html/image_path, confidence nếu parser thật sự trả, provenance và warnings. Tránh 'điền' confidence giả. Dùng khóa document/run để tách bản xuất theo option khác nhau. Không gộp toàn bộ ảnh vào string base64 lớn nếu chỉ cần đường dẫn trên filesystem.

## 5.4. Vòng đời xử lý

Job có trạng thái queued → processing → succeeded/failed/cancelled; mỗi bước lưu thời điểm, elapsed time, tool version và đường dẫn output. Ghi kết quả ra tệp tạm, kiểm tra trước khi rename nguyên tử; tránh cho frontend tải file đang ghi dở. Retry phải xác định dùng cache hay force thực thi lại, đồng thời không trộn output của hai job.

## 5.5. Kế hoạch fallback

Nếu text extraction đọc được cấu trúc hợp lệ, dùng text trực tiếp để giảm sai khác; nếu text layer hỏng/thiếu, chuyển page/region sang OCR. Nếu công thức thất bại tại bước LaTeX → OMML, sử dụng crop ảnh gốc có liên kết nguồn hoặc đánh dấu chờ sửa; nếu bảng không ổn định, ưu tiên ảnh bảng hơn một bảng Word chứa dữ liệu sai. Tất cả fallback phải được ghi nhận.

## 5.6. Quyết định kiến trúc và trade-off

Pipeline synchronous CLI đơn giản cho nghiên cứu và demo một tệp; API web có job queue thích hợp khi phải xử lý nhiều tài liệu nặng. Đổi lấy tính chỉnh sửa có thể mất một phần pixel-perfect fidelity; đổi lấy giống bố cục tuyệt đối có thể phải giữ một số đối tượng dạng ảnh. Không triển khai distributed architecture khi workload chưa chứng minh nhu cầu.

# CHƯƠNG 6. TIẾP NHẬN, PHÂN LOẠI VÀ CHUẨN HÓA PDF

## 6.1. Kiểm tra tệp đầu vào

Kiểm tra phần mở rộng, magic header %PDF-, parser open thành công, số trang, tình trạng mã hóa/password, kích thước trang và giới hạn tài nguyên. Magic header chỉ là preflight ban đầu, không thay thế việc parse. Tránh tin filename do client gửi; tạo tên lưu server-side và tránh path traversal/symlink escape.

## 6.2. Chiến lược text/scan

Thu thống kê trên toàn bộ trang hoặc tập trang đại diện: mật độ ký tự có thể trích xuất, tỷ lệ ảnh phủ trang, lỗi Unicode và bố cục có bao nhiêu block. Chọn chế độ text, OCR hoặc hỗn hợp từng trang. Không coi 'có vài ký tự' là đủ để tắt OCR vì nhiều PDF scan có số trang hoặc header text nổi trên ảnh.

## 6.3. Xử lý rotation, cropbox và DPI

Trước nhận dạng, chuẩn hóa hướng trang và mapping tọa độ. Render ở DPI phù hợp độ cao ký tự; khi tăng DPI đồng thời tăng RAM và thời gian. Phân biệt DPI của ảnh gốc với DPI rasterization từ PDF vector. Luôn giữ bản gốc để truy ngược khi OCR làm mất nét.

## 6.4. Cô lập run và cache

Repository đã có `prepare_run_dir()` và `compute_doc_id()` dùng hash nội dung để tránh trộn tài liệu khác nhau. Cần mở rộng cache key theo parser/version/config nếu một PDF được xử lý bằng nhiều tùy chọn, kèm checksum/manifest và kiểm tra sự hiện diện đầy đủ của artifact. Nếu cache thiếu một file cần thiết, chạy lại có kiểm soát.

## 6.5. Structured extraction

Sau parser, chuẩn hóa các loại text, title, table, image, equation; giữ chỉ số trang từ 0 ở dữ liệu và đổi sang 1 khi hiển thị. Xử lý caption, footnote và thứ tự đọc dựa theo quan hệ khu vực, không chỉ sắp xếp tọa độ y tăng dần vì tài liệu hai cột sẽ bị trộn dòng.

## 6.6. Kiểm tra đầu ra parser

Bắt lỗi null bbox, bbox vượt ranh trang, đường dẫn ảnh không tồn tại, block trùng lặp, công thức có dấu phân cách không cân bằng, table HTML không đóng tag; xuất danh sách warning. Không tự sửa các ký hiệu toán khó bằng quy tắc từ điển nếu chưa chứng minh tính tương đương về ngữ nghĩa.

# CHƯƠNG 7. NHẬN DẠNG CÔNG THỨC TOÁN HỌC VÀ WORD EQUATION

## 7.1. Phân loại ký hiệu và biểu thức

Phân biệt inline math và display math; công thức rời, chuỗi phép biến đổi, chỉ số hai cấp, ma trận và bảng dấu. Nhận dạng số mũ không chỉ là phân loại ký tự: vị trí tương đối của superscript/subscript là một quan hệ cấu trúc. Hệ phương trình gồm ngoặc lớn và biểu thức nhiều hàng không thể xử lý như một dòng văn bản thuần.

## 7.2. Kết quả LaTeX trung gian

Parser có thể trả \\(x^2\\), \\(\\frac{a}{b}\\), \\(\\sqrt[n]{x}\\), \\(\\sum_{i=1}^n a_i\\) và các environment như array/matrix. Cần tách raw latex, normalized latex và result status để kiểm soát từng bước; không ghi đè bản raw khi làm hậu xử lý. LaTeX hợp lệ về cú pháp chưa chứng minh ký hiệu khớp PDF gốc.

## 7.3. Chuẩn hóa lệnh kiểu cũ

Các pattern có trong code hiện hữu gồm biến đổi `\\bf` thành `\\mathbf`, sửa lệch `\\left`/`\\right`, xử lý dấu double-prime OCR nhầm ngoặc kép và một số lỗi encoding font tiếng Việt. Mỗi quy tắc cần regression test trên mẫu dương và âm để tránh sửa nhầm biểu thức vốn đã đúng. Khi không thể xác định chắc chắn, giữ nguyên kèm warning.

## 7.4. Quy tắc chuyển LaTeX → OMML

Sử dụng Pandoc để dựng Word Equation ở dạng `m:oMath`; xác nhận tài liệu sau chuyển đổi qua `word/document.xml` và mở bằng Word. Cần kiểm tra các thành phần như m:f (fraction), m:sSup/m:sSub (chỉ số), m:rad (căn), m:nary (toán tử tổng/tích), m:m (matrix) trong một số test đại diện thay vì chỉ đếm số lượng m:oMath.

## 7.5. Không đồng nhất 'đếm Equation' với accuracy

Một tệp có 100 đối tượng Equation vẫn có thể sai 100 ký hiệu. Đánh giá theo formula match có chuẩn hóa, character/symbol accuracy và kiểm tra thủ công với biểu thức dài. Báo cáo riêng tỷ lệ chuyển thành OMML, tỷ lệ phải fallback ảnh và tỷ lệ sai ngữ nghĩa do OCR; không gộp thành một chỉ số 'độ chính xác'.

## 7.6. Công thức cực khó và fallback ảnh

Các trường hợp xác suất sai cao gồm hệ nhiều dấu ngoặc, căn phủ nhiều dòng, ký hiệu chữ viết tay, biểu thức trong bảng và công thức chồng nhau. Nếu parser có crop từ PDF gốc, chèn ảnh công thức vào DOCX để bảo toàn thị giác với cờ `not_editable`. Đặt caption/source page hoặc metadata giúp người dùng biết vị trí cần sửa thủ công.

## 7.7. Chính sách kiểm thử công thức

Bộ mẫu tối thiểu phải có phân số lồng, căn nhiều bậc, lũy thừa/chỉ số, tích phân, đạo hàm bậc cao, tổng/tích, giới hạn, khoảng, vector, ma trận, hệ phương trình, logic, dấu tiếng Việt lân cận và môi trường array/align. Test vừa kiểm tra XML vừa render để xác định glyph không bị thay thế hoặc căn chỉnh sai.

# CHƯƠNG 8. KHÔI PHỤC BỐ CỤC, BẢNG VÀ HÌNH ẢNH

## 8.1. Xác định thứ tự đọc

Với trang một cột, thứ tự theo y có thể là baseline; với hai cột cần phân vùng theo cột rồi đọc từ trên xuống trong từng cột. Headline toàn chiều rộng, hình trải hai cột và footnote cần được xử lý thành ngoại lệ. Bbox là dấu hiệu hữu ích nhưng không cung cấp đủ ngữ nghĩa mọi cấu trúc.

## 8.2. Nhiều cột và section của Word

Word cho phép `sectPr` khai báo khổ giấy, lề, orientation và cột; có thể chèn column break để giữ luồng. Tuy nhiên cách chèn section sai có thể tạo trang trắng hoặc đảo thứ tự. Module `llm/src/layout.py` local đang có heuristic nhóm block hẹp theo x0; đây là phần đang phát triển, chưa được xác thực trên corpus đủ lớn.

## 8.3. Bảng có gộp ô

Bảng không chỉ là các dòng có ký tự '|' hay khoảng trắng. Cần xác định cell và quan hệ rowspan/colspan; khi tái dựng Word phải giữ ma trận hàng/cột hợp lệ. Các bảng biến thiên chứa mũi tên, dấu ±, đường kẻ đặc biệt nên thường cần chế độ tái dựng riêng hoặc fallback ảnh để tránh đổi thứ tự dấu.

## 8.4. Hình học và ảnh minh họa

Hình vẽ có nhãn A, B, C và mũi tên vector cần được giữ nguyên, không thể thay bằng mô tả tự sinh. Với ảnh, chỉ lưu trữ đường dẫn tài nguyên, crop và kích thước theo bbox. Mỗi hình nên có chú thích/nguồn trang và kiểm tra xem ảnh bị co giãn không đồng tỷ lệ hay bị clipping khi chuyển Word.

## 8.5. Header, footer và đánh số trang

Nhận biết header/footer lặp lại giữa các trang để tránh chèn vào giữa nội dung; đưa page-number vào field Word thay vì ghi text tĩnh. Với tài liệu trang hỗn hợp portrait/landscape, mỗi section cần khổ giấy đúng, còn số trang nhất quán. Không tự điền mục lục với số trang chưa render.

## 8.6. Chất lượng theo lớp

Một báo cáo layout cần chấm riêng: thứ tự đọc đúng, số cột đúng, hình/bảng giữ nguyên, đúng chiều rộng/căn lề và mức sai lệch raster. Không khẳng định pixel-perfect cho mọi PDF nếu xử lý bằng dòng văn bản Word động và engine dàn trang khác PDF.

# CHƯƠNG 9. ẢNH MỜ, NHÒE, NHIỄU VÀ PDF SCAN

## 9.1. Các dạng suy giảm chất lượng

Phân biệt Gaussian blur, motion blur, ảnh thiếu nét do focus, nén JPEG tạo ringing/blocking, nhiễu salt-and-pepper, nền giấy vàng/xám, trang bị nghiêng và độ phân giải thấp. Mỗi loại ảnh hưởng khác nhau đến ký hiệu toán; ví dụ dấu nguyên hàm, số 1, ký tự l/I và dấu chấm rất nhạy với blur.

## 9.2. Phân tích chất lượng trang

Ước lượng độ rõ (Laplacian variance chỉ như một chỉ báo), noise, skew, resolution thực và kích thước ký tự. Không dùng một threshold đơn nhất để kết luận 'ảnh mờ' trên mọi DPI, vì văn bản in mảnh, hình vẽ hoặc nền texture có thể làm kết quả lệch. So sánh chất lượng trước và sau tiền xử lý bằng OCR downstream mới có ý nghĩa.

## 9.3. Chuỗi tiền xử lý thận trọng

Luồng đề xuất: giữ bản gốc → phát hiện hướng/deskew → crop vùng → grayscale/contrast nhẹ → thử de-noise/binarization theo điều kiện → OCR trên cả ảnh gốc và một vài biến thể → chọn kết quả qua rule/đánh giá có chứng cứ. Tránh làm sharpening và interpolation nhiều lần liên tiếp vì dễ sinh nét giả.

## 9.4. Quy tắc chọn OCR theo vùng

Văn bản thường và công thức có thể cần mô hình khác nhau; công thức nhỏ nên crop riêng với vùng đệm, tăng scale không thay nội dung gốc. Sau OCR, liên kết từng kết quả với bbox và ảnh nguồn. Trường hợp công thức được đọc khác nhau giữa nhiều biến thể, đưa vào hàng chờ kiểm tra thay vì lấy một kết quả bất kỳ.

## 9.5. Thí nghiệm suy giảm tổng hợp

Từ bộ PDF có ground truth, render một bộ ảnh chuẩn rồi tạo blur, noise, skew, giảm resolution theo cấp độ rõ ràng. Cố định random seed và lưu tham số biến đổi. Báo cáo accuracy riêng cho mỗi cấp độ và so với ảnh gốc; không đánh đồng cải thiện hình ảnh thị giác với cải thiện OCR.

## 9.6. Trường hợp không thể phục hồi

Khi hai glyph khác nhau cho ảnh sau suy giảm gần như không phân biệt, suy luận từ hình ảnh đơn lẻ không thể bảo đảm phục hồi ký hiệu đúng. Hệ thống cần lưu vùng gốc, loại lỗi, mức tin cậy có căn cứ hoặc cờ review. Không dùng mô hình ngôn ngữ tự ý thay đổi công thức để nó 'có vẻ hợp lý' rồi trình bày như bản chuyển đổi chính xác.

# CHƯƠNG 10. THIẾT KẾ BACKEND, GIAO DIỆN VÀ AN TOÀN

## 10.1. API hợp lý cho conversion

Thiết kế đích gồm `POST /api/conversions` upload; `GET /api/conversions/{id}` trạng thái; `GET /api/conversions/{id}/result` tải DOCX; `GET /api/conversions/{id}/report` tải JSON báo cáo; `DELETE /api/conversions/{id}` xóa job. Đây là API đề xuất, không mặc định đã tồn tại trong code. Lỗi nên trả 400/413/415/422/404/500 theo contract rõ ràng.

## 10.2. Bảo vệ upload

Kiểm tra extension, signature, parse thực; giới hạn dung lượng, số trang, thời gian CPU và decompression; chống zip/pdf bomb ở mức tài nguyên; hạn chế đường dẫn truy cập và danh sách MIME output; không trả stack trace, đường dẫn server hoặc API key cho client.

## 10.3. Theo dõi job và lỗi

Khi OCR nặng, API upload trả job_id; worker dùng timeout/cancellation và quy tắc retry idempotent. Job lưu trạng thái đầy đủ, đường dẫn output cuối cùng, cảnh báo từng trang và lỗi có mã. Frontend poll trạng thái có backoff; không lặp tạo job khi request trước đó còn xử lý mà không có idempotency key.

## 10.4. Giao diện người dùng

Giao diện tối giản với upload, bảng job, nhãn trạng thái, biểu đồ tiến trình, preview PDF/DOCX cạnh nhau, danh sách công thức được giữ ảnh và nút download. Không cần giao diện chat. Với tài liệu dài, preview tải từng trang thay vì render toàn bộ PDF vào DOM cùng lúc.

## 10.5. Bảo mật dữ liệu học tập

PDF có thể chứa dữ liệu nội bộ hoặc thông tin người dùng. Nếu lưu server, cần chính sách giữ/xóa, quyền truy cập job, tên file ngẫu nhiên, hạn chế CORS theo origin hợp lệ và log đã redact. Nếu demo local, vẫn phải tránh để runtime/cache/data chứa PDF cá nhân bị commit vào Git.

## 10.6. Quan sát hệ thống

Log theo request_id/job_id với các mốc upload, classify, parse, normalize, export, preflight và thời gian mỗi giai đoạn. Metric theo số trang xử lý, throughput, memory peak, tỉ lệ parser fail và số cảnh báo. Không ghi toàn bộ công thức PDF cá nhân vào log production theo mặc định.

# CHƯƠNG 11. ĐỐI CHIẾU MÃ NGUỒN THỰC TẾ

## 11.1. Phạm vi kiểm tra repository

Repository GitHub: `ducnhan123-co/DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026`, nhánh `main`, đã kiểm tra trong phiên làm việc ngày 15/10/2026. Mã nguồn liên quan trực tiếp conversion nằm ở `llm/src/run_mineru.py`, `llm/src/build_docx.py` và bản `llm/src/layout.py` chưa commit tại máy. Các folder backend/frontend hiện có vẫn chứa chức năng từ hướng nghiên cứu cũ; không coi chúng là sản phẩm conversion-only hoàn tất.

## 11.2. Những thành phần đã có

`run_mineru.py` có hash theo nội dung, run directory, luồng adapter MinerU và xử lý kết quả JSON/Markdown/ảnh. `build_docx.py` có hậu xử lý LaTeX/tiếng Việt, fallback hình cho một số trường hợp, dựng DOCX bằng Pandoc và xử lý style, số trang. Test đã có trường hợp ngăn tạo DOCX nửa chừng, kiểm tra bảng Word và fallback ảnh.

## 11.3. Module layout đang phát triển

File `llm/src/layout.py` ở working tree thực hiện ước lượng cỡ chữ, phát hiện cột từ bbox, chèn Word section/column break và canh kích thước ảnh. Heuristic này có nguy cơ nhận sai trên trang có floating image hoặc heading full width, nên phải benchmark trước khi ghi là 'bảo toàn bố cục chính xác'. Giữ thay đổi chưa commit, không reset và không gộp nhầm vào nhánh phát hành.

## 11.4. CLI conversion-only đã bổ sung

File `pdf_to_word.py` mới tạo một đường chạy chỉ chuyển PDF → DOCX, không khởi động thành phần không liên quan. CLI có `--pdf`, `--output`, `--tier`, `--method`, `--force`, `--layout`, kiểm tra magic header, gọi MinerU và preflight tệp Word. Tệp `conversion_report.json` lưu kết quả cơ bản; đây là bước tách pipeline phục vụ đề tài, chưa chứng minh API/UI đã được chuyển đổi.

## 11.5. Kết quả kiểm thử xác minh được

Trên máy Mac ngày 15/10/2026 đã chạy `python3 -m pytest tests/test_pdf_to_word_cli.py tests/test_build_docx_fixes.py tests/test_layout.py -q --disable-warnings --maxfail=1`: 19 bài đạt, 5 warning. Điều này chứng minh các unit test trong phạm vi đã chạy đạt; không chứng minh khả năng xử lý mọi PDF hay chất lượng OCR trên scan nhòe. CLI `--help` và `py_compile` cũng chạy được.

## 11.6. Vấn đề còn tồn tại

Chưa xác nhận chạy E2E đầy đủ trên tập chuẩn; chưa có benchmark định lượng CER/Formula match/layout; API/front-end cũ cần tái cấu trúc để chỉ tập trung conversion; phụ thuộc mô hình/parser cần khóa version; cơ chế job queue/retention và đối chiếu render đa tài liệu cần bổ sung. Các hạng mục chưa xong sẽ để trạng thái 'đề xuất' hoặc 'cần thực hiện'.

# CHƯƠNG 12. THỬ NGHIỆM VÀ ĐÁNH GIÁ CHẤT LƯỢNG

## 12.1. Xây dựng corpus công bằng

Phân nhóm PDF chữ rõ, PDF scan rõ, scan mờ, trang nhiều cột, bảng thường, bảng gộp ô, bảng biến thiên, hệ phương trình, ma trận, hình học, PDF font legacy và hỗn hợp. Mỗi mẫu lưu nguồn, checksum, giấy phép nếu dùng dữ liệu công khai, số trang, điều kiện tạo scan, ground truth và ngày chạy. Tránh chọn riêng các mẫu thành công để báo cáo.

## 12.2. Ground truth cần thiết

Với text dùng bản chép chuẩn UTF-8; với công thức cần cấu trúc LaTeX hoặc biểu diễn chuẩn được giám khảo xác nhận và vùng ảnh; với layout cần nhãn block, thứ tự đọc, số cột và vùng bảng/ảnh; với Word cần kiểm tra OOXML lẫn khả năng mở/edit. Không thể tính CER đáng tin nếu ground truth cũng được OCR tự động từ chính ảnh đang đánh giá.

## 12.3. Nhóm metric

CER = (S+D+I)/N trên chuỗi ký tự tham chiếu; WER áp dụng cho từ. Formula exact match chỉ sau quy tắc canonicalization đã định nghĩa; structural equation validity là tỉ lệ công thức có OMML hợp lệ. Layout đo độ đúng thứ tự đọc/cột/cell; ảnh so sánh render có thể dùng SSIM/IoU hoặc phân tích trực quan, nhưng phải nêu cách chuẩn hóa kích thước và quy tắc chấp nhận.

## 12.4. Benchmark hiệu suất

Đo wall-clock, thời gian parse/export, CPU/GPU/RAM peak và kích thước PDF/DOCX theo số trang, loại tài liệu. Nêu tên máy, phiên bản Python, MinerU, Pandoc, model, chế độ CPU/GPU và độ phân giải. Chạy warmup và nhiều lần với cùng input; báo median/p95 nếu số phép đo đủ, không gán con số từ tài liệu nhà sản xuất cho máy của nhóm.

## 12.5. Bảng kết quả chưa có số liệu

Đề xuất các cột: Dataset ID | Loại PDF | Pages | Text CER | Formula exact match | OMML count | Table/layout success | Fallback count | Time | Peak RAM | Reviewed by. Không chèn giá trị giả. Dấu '—' hoặc 'chưa đo' nghĩa là nhóm chưa có ground truth hoặc chưa chạy thí nghiệm.

## 12.6. Kiểm thử regression

Tái chạy bộ case đã có sau mỗi sửa đổi normalization/layout. Khi một quy tắc làm một công thức đúng bị biến thành sai, thêm regression test âm rồi sửa quy tắc. CI cần phân lớp pure function unit test (nhanh) với integration MinerU/Pandoc và E2E có file PDF (chậm).

## 12.7. Quy trình xác minh tài liệu thực

Với mỗi PDF: lưu checksum/ảnh gốc; chạy parser; lưu Markdown/JSON; dựng DOCX; kiểm tra ZIP/XML; render Word ra PDF; đặt cặp trang cạnh nhau; đánh dấu công thức, bảng và hình khác; đếm lỗi; tổng hợp báo cáo; cho người thứ hai duyệt các case rủi ro. Chỉ gọi 'đạt' nếu tiêu chí đầu ra cụ thể được kiểm.

# CHƯƠNG 13. THẢO LUẬN, RỦI RO VÀ HƯỚNG PHÁT TRIỂN

## 13.1. Nguồn lỗi và ưu tiên sửa

Sai sót có thể đến từ scan, parser segmentation, OCR text, model công thức, chuyển LaTeX → OMML, mapping layout, Pandoc/Word renderer hoặc người kiểm thử. Phân loại theo giai đoạn trước khi sửa: nếu ký hiệu sai đã xuất hiện ở Markdown, sửa DOCX stylesheet sẽ không giải quyết được.

## 13.2. Rủi ro về chất lượng toán học

Một dấu âm, dấu mũ hoặc chỉ số thay đổi có thể làm sai hoàn toàn nội dung toán. Chất lượng công thức phải đặt trên thẩm mỹ; tốt hơn là giữ vùng ảnh gốc kèm cảnh báo hơn là tự sửa thành một công thức trông hợp lý nhưng không đúng nguồn.

## 13.3. Khả năng mở rộng

Có thể bổ sung queue/worker, chạy OCR theo trang, cache theo content + config, điều chỉnh RAM batch size, trang xem trước và dashboard kiểm tra lỗi. Mọi tối ưu phải được đánh giá trên tốc độ và chất lượng, không chỉ tăng throughput bằng cách bỏ qua bước kiểm soát.

## 13.4. Giới hạn đồ án tại thời điểm rà soát

Báo cáo hiện là thiết kế và tổng hợp hiện trạng kiểm thử module. Chưa có số liệu thực nghiệm xác minh chất lượng toàn hệ thống trên bộ case quy định, chưa có bằng chứng dùng được 'mọi loại công thức' hay phục hồi ký tự bị mờ hoàn toàn. Các kết luận thành công/độ chính xác phần này được để mở để nhóm điền sau khi có số liệu.

# CHƯƠNG 14. KẾT LUẬN

Đề tài tập trung vào bài toán chuyển đổi tài liệu PDF toán học sang Word với ba giá trị cốt lõi: công thức toán học ở định dạng chỉnh sửa được, bố cục có cấu trúc hợp lý và khả năng xử lý/nhận biết giới hạn của ảnh scan chất lượng thấp. Các bước từ nhận tài liệu đến xuất DOCX đã được thiết kế rõ ràng, với phân biệt được mã nguồn có sẵn, các phần đang phát triển và mục cần làm trước nghiệm thu.

Hiện tại pipeline MinerU–Pandoc–DOCX và các unit tests cung cấp nền tảng kỹ thuật. Kết quả 19/19 unit tests đạt trong phạm vi kiểm tra không thay thế đánh giá E2E và đo accuracy. Các nhóm cần hoàn thiện chuyển đổi giao diện/API, thu thập ground truth, thử với PDF khó, chuẩn hóa bảng kết quả và cung cấp minh chứng trực quan trước khi nộp báo cáo cuối cùng.

# TÀI LIỆU THAM KHẢO

[1] Adobe, PDF Reference và ISO 32000 (tra cứu phiên bản áp dụng cho mẫu dữ liệu).

[2] PyMuPDF, TextPage và Page.get_text, https://pymupdf.readthedocs.io/en/latest/textpage.html

[3] PyMuPDF, Text Extraction, https://pymupdf.readthedocs.io/en/latest/recipes-text.html

[4] OpenDataLab, MinerU official repository, https://github.com/opendatalab/MinerU

[5] Pandoc User’s Guide, DOCX và math rendering, https://pandoc.org/MANUAL.html

[6] Microsoft Learn, Microsoft 365 Math documentation, https://learn.microsoft.com/en-us/office/math/

[7] Microsoft Learn, LaTeX Support in Microsoft 365, https://learn.microsoft.com/en-us/office/math/latex

[8] Microsoft Support, Editing Equations in Word, https://support.microsoft.com/en-us/word/editing-equations-created-using-microsoft-equation-editor

[9] Tesseract Documentation, Improving the quality of the output, https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html

[10] python-docx documentation, https://python-docx.readthedocs.io/en/latest/

[11] Project source, https://github.com/ducnhan123-co/DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026

[12] W3C, MathML Core, https://www.w3.org/TR/mathml-core/

[13] OpenCV, image thresholding and geometric transforms, https://docs.opencv.org/

[14] ISO/IEC 29500, Office Open XML file formats (WordprocessingML and Math).

# PHỤ LỤC A. BỘ KIỂM THỬ VÀ DỮ LIỆU GROUND TRUTH

Các case dưới đây là THIẾT KẾ KIỂM THỬ, không phải chứng cứ đã chạy hoặc số liệu benchmark. Mỗi case cần một PDF có nguồn hợp pháp, đáp án/nhãn tham chiếu, output DOCX, ảnh so sánh và trạng thái PASS/FAIL có kiểm tra.

## A.01. PDF chữ Unicode rõ

Mục đích: Đọc đúng Unicode và không đưa sang OCR khi text layer đáng tin. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đo CER và giữ Unicode tiếng Việt. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.02. PDF scan 300 DPI

Mục đích: OCR chữ và công thức, bảo toàn thứ tự đọc. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đối chiếu vùng scan gốc với text/OMML. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.03. PDF scan 150 DPI

Mục đích: Ghi nhận suy giảm ký hiệu nhỏ. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So CER/Formula match với bản 300 DPI. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.04. PDF mờ Gaussian

Mục đích: Không làm mất dấu và chữ nhỏ sau tiền xử lý. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đo mức blur, báo số lỗi theo nhóm ký hiệu. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.05. PDF nhòe do chuyển động

Mục đích: Không biến cặp nét song song thành một. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đối chiếu dấu bằng và dấu chia. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.06. PDF có JPEG artifacts

Mục đích: Giảm kết dính nét chữ, không biến dạng bảng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So ảnh input và kết quả OCR. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.07. PDF có skew

Mục đích: Nhận ra góc nghiêng và deskew hợp lý. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Xem tỷ lệ đọc đúng sau deskew. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.08. PDF nhiều kích cỡ trang

Mục đích: Duy trì khổ giấy riêng theo section. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra w:pgSz và render. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.09. PDF có xoay 90 độ

Mục đích: Dựng đúng hướng chữ. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra rotation/cropbox mapping. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.10. PDF một cột

Mục đích: Giữ trật tự đoạn/thứ tự công thức. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So sequence block và ảnh. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.11. PDF hai cột

Mục đích: Không đọc xen kẽ hai cột. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Nhóm column order theo bbox. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.12. PDF có heading toàn chiều ngang

Mục đích: Không gắn heading vào cột trái riêng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So segmentation sau layout. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.13. PDF có footnote

Mục đích: Không chèn footnote vào body giữa câu. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đối chiếu vị trí/chú thích. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.14. PDF có hình trải hai cột

Mục đích: Giữ caption và chiều rộng hình. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So bbox và section breaks. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.15. PDF có bảng đơn giản

Mục đích: Tạo bảng Word thực và đủ ô. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Đếm cell và so text. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.16. PDF có bảng gộp ô

Mục đích: Giữ colspan/rowspan hợp lý. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So hình học hàng/cột Word. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.17. PDF có bảng biến thiên

Mục đích: Giữ dấu, mũi tên và thứ tự hàng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So từng dấu mốc và đường kẻ. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.18. PDF có bảng chân trị

Mục đích: Không mất T/F, dấu phủ định. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So từng cell. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.19. PDF có ảnh hình học

Mục đích: Không mất đỉnh/nhãn/đường nét. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So ảnh crop và ảnh DOCX. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.20. PDF có đồ thị hàm số

Mục đích: Không cắt trục/nhãn toạ độ. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So đủ hình và caption. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.21. PDF ký tự font cũ VNI/TCVN3

Mục đích: Không làm sai từ đã đúng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra Unicode trước-sau. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.22. PDF phương trình inline

Mục đích: Giữ vị trí giữa câu và Word Equation. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So XML và render. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.23. PDF phương trình display

Mục đích: Công thức đặt dòng riêng, không vỡ đoạn. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So alignment/OMML. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.24. PDF có phân số lồng

Mục đích: Giữ đúng cấp tử/mẫu. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So structural OMML và ảnh. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.25. PDF có căn bậc cao

Mục đích: Giữ dấu căn và chỉ số. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra m:rad. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.26. PDF có đạo hàm dấu phẩy

Mục đích: Phân biệt prime/double prime. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So glyph và text LaTeX. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.27. PDF có chỉ số trên dưới

Mục đích: Giữ thứ tự exponent/subscript. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra m:sSup/m:sSub. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.28. PDF có tích phân/tổng

Mục đích: Giữ cận và toán tử lớn. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra m:nary và render. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.29. PDF ma trận

Mục đích: Giữ đúng hàng/cột và ngoặc. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra m:m và bbox. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.30. PDF hệ phương trình

Mục đích: Giữ ngoặc hệ nhiều hàng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So XML và ảnh. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.31. PDF có align/array

Mục đích: Không làm lệch ngoặc và phép biến đổi. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra LaTeX normalization. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.32. PDF nhiều ảnh cạnh nhau

Mục đích: Giữ thứ tự và caption riêng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So thứ tự media reference. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.33. PDF không có text layer

Mục đích: Không xuất ra DOCX trắng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra OCR pathway. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.34. PDF text layer hỏng

Mục đích: Có fallback OCR theo vùng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: So bản text gốc và OCR. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.35. PDF lỗi/truncated

Mục đích: Báo 4xx/failed rõ ràng. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Không trả DOCX hỏng. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.36. PDF sai phần mở rộng

Mục đích: Từ chối định dạng không hợp lệ. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra extension + header + parser. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.37. PDF số trang quá lớn

Mục đích: Áp giới hạn tài nguyên. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Không giữ process vô hạn. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.38. PDF đặt tên chứa ký tự lạ

Mục đích: Không tạo đường dẫn nguy hiểm. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Sanitize filename. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.39. PDF có nhiều file giống tên

Mục đích: Không dùng nhầm cache. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Kiểm tra hash nội dung. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

## A.40. Cùng PDF khác cấu hình OCR

Mục đích: Không tái sử dụng output cấu hình sai. Tiền điều kiện: PDF mẫu có metadata nguồn và ít nhất một trang có nhãn đối chứng. Quan sát bắt buộc: Cache key gồm config/version. Kiểm thử xác nhận cả nội dung ở biểu diễn trung gian, OOXML trong Word và kết quả render; không xem việc subprocess exit code 0 là đủ.

Quy trình: (1) lưu SHA-256 của PDF; (2) chạy chế độ auto để thu ảnh/Markdown/content_list; (3) xác định block mục tiêu và trang; (4) xuất DOCX tạm; (5) kiểm tra ZIP hợp lệ và Word Equation thực; (6) render, đánh dấu các chênh lệch; (7) ghi PASS/FAIL và bằng chứng. Nếu nhận dạng sai cần gắn lỗi với đúng stage và giữ ảnh gốc.

Biến thể dạng rõ, không tiền xử lý: Thiết lập baseline để đối chiếu; lưu checksum, parser config và thời gian từng bước. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng suy giảm nhẹ, có kiểm soát: Chụp ảnh trước-sau, kiểm tra xem thuật toán tăng chất lượng có phá dấu nhỏ hay không. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

Biến thể dạng chất lượng thấp: Kiểm tra fallback ảnh/warning; không 'bịa' lại công thức không thể đọc. Kết quả phải ghi 'chưa chạy' cho đến khi có log, file nguồn và người đối chiếu. Tiêu chí thất bại: sai ký hiệu/toán, mất vùng dữ liệu, đảo reading order, xuất DOCX hỏng hoặc không báo cảnh báo khi fallback cần thiết.

# PHỤ LỤC B. KIỂM TRA HỆ THỐNG VÀ TESTING CHECKLIST

## B. Input integrity

Kiểm tra chính: Có PDF magic header. Điều kiện nghiệm thu: Mở được bằng parser không báo hỏng. Lưu ý vận hành: Giữ original hash. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Isolation

Kiểm tra chính: Mỗi run theo hash và config. Điều kiện nghiệm thu: Không lẫn ảnh của PDF khác. Lưu ý vận hành: Kiểm tra concurrent jobs. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. OCR routing

Kiểm tra chính: Scan sang OCR, text tốt giữ extraction. Điều kiện nghiệm thu: Không dừng vì vài ký tự header. Lưu ý vận hành: Có sample hỗn hợp. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Parser adapter

Kiểm tra chính: Hỗ trợ output version thực tế. Điều kiện nghiệm thu: Báo lỗi định dạng unsupported. Lưu ý vận hành: Pin MinerU version. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Math normalization

Kiểm tra chính: Không đổi công thức đã đúng. Điều kiện nghiệm thu: Regression dương và âm. Lưu ý vận hành: Giữ raw latex. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. OMML generation

Kiểm tra chính: Có m:oMath đúng cấu trúc. Điều kiện nghiệm thu: Word có thể sửa biểu thức. Lưu ý vận hành: So ảnh gốc. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Table rendering

Kiểm tra chính: Không rơi cột/hàng. Điều kiện nghiệm thu: Có image fallback. Lưu ý vận hành: Kiểm tra merged cells. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Column layout

Kiểm tra chính: Không chèn trắng hoặc đảo đoạn. Điều kiện nghiệm thu: Kiểm tra 1 cột, 2 cột và heading toàn chiều. Lưu ý vận hành: Heuristic cần corpus. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Media

Kiểm tra chính: Ảnh tồn tại, không crop sai. Điều kiện nghiệm thu: Caption đúng trang. Lưu ý vận hành: Tránh path traversal. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. DOCX atomicity

Kiểm tra chính: Chỉ công bố output sau rename. Điều kiện nghiệm thu: Không tải .building.docx. Lưu ý vận hành: Giả lập job fail. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Status tracking

Kiểm tra chính: queued/processing/succeeded/failed. Điều kiện nghiệm thu: Không trả success khi output lỗi. Lưu ý vận hành: Log trace_id. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Security

Kiểm tra chính: Giới hạn file/time/RAM. Điều kiện nghiệm thu: Không leak PDF qua logs. Lưu ý vận hành: Chặn tải khác owner. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Error handling

Kiểm tra chính: Lỗi parser có code rõ. Điều kiện nghiệm thu: Không stack trace cho client. Lưu ý vận hành: Giữ diagnosic logs. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Metrics

Kiểm tra chính: CER/Formula/layout độc lập. Điều kiện nghiệm thu: Bắt buộc ground truth. Lưu ý vận hành: Không tự điền benchmark. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

## B. Regression

Kiểm tra chính: Pure tests, integration, E2E phân lớp. Điều kiện nghiệm thu: CI có test fixture nhỏ. Lưu ý vận hành: Tránh model download trong unit. Nhóm phải gắn output PDF/DOCX, ảnh render, cấu hình thiết bị và tình trạng kiểm tra; không ghi PASS chỉ dựa vào suy đoán hoặc unit test không liên quan.

# PHỤ LỤC C. ĐỐI CHIẾU YÊU CẦU VỚI MODULE VÀ TRẠNG THÁI

FR-01 → pdf_to_word.py / backend upload adapter → kiểm tra file và tài nguyên → CLI validation có unit test; web adapter cần refactor.

FR-02 → llm/src/run_mineru.py → routing OCR và parse → có code, cần E2E PDF hỗn hợp.

FR-03 → MinerU content_list/structured data → block + page/bbox → có thành phần, cần fixture đa phiên bản.

FR-04 → llm/src/build_docx.py → normalize LaTeX tiếng Việt → có regression tests, chưa benchmark ký hiệu.

FR-05 → Pandoc/OMML → tạo Word Equation → có test cấu trúc cơ bản, cần Word visual QA.

FR-06 → llm/src/layout.py → tái dựng cột/lề/ảnh → đang phát triển local và cần nghiệm thu.

FR-07 → md_to_docx temp+atomic rename → đã có test → cần kiểm tra tải từ API.

FR-08 → job model/status endpoint → legacy có hạ tầng job, cần tinh giản chỉ conversion.

FR-09 → download DOCX → có thành phần export cũ, cần làm mới contract và E2E.

FR-10 → conversion_report.json, cảnh báo/so sánh → báo cáo CLI cơ bản; metric chưa triển khai hoàn chỉnh.

# PHỤ LỤC D. HƯỚNG DẪN TÁI LẬP

Điều kiện: clone chính repository dự án, cài Python dependencies từ file requirements thích hợp; cài MinerU CLI tương thích, Pandoc, backend các thư viện cần. Ghi rõ phiên bản, OS, architecture và bộ mô hình tải về. Không khuyến nghị 'pip install latest' cho thí nghiệm so sánh vì kết quả có thể thay đổi giữa lần chạy.

Chạy thử CLI: `python3 pdf_to_word.py --help`, sau đó `python3 pdf_to_word.py --pdf llm/input/ToanNinhBinh.pdf --output output/toan.docx --layout` nếu môi trường có đủ parser. Nếu thiếu MinerU hoặc model, đánh dấu môi trường chưa sẵn sàng, không coi là lỗi accuracy. Không cần khởi động thành phần sinh văn bản khác.

Unit test đã chạy: `python3 -m pytest tests/test_pdf_to_word_cli.py tests/test_build_docx_fixes.py tests/test_layout.py -q --disable-warnings --maxfail=1`. Kết quả tại thời điểm rà soát là 19 passed, 5 warnings; tái chạy sau mỗi commit để bảo đảm trạng thái mới.

Trong từng run, lưu artifacts: input hash, parser stdout/stderr đã redact, Markdown, JSON blocks, crop images, work Markdown, output DOCX, OOXML validation, rendered PDF, annotated side-by-side images, `conversion_report.json`, summary CSV. Không commit PDF riêng tư hoặc tệp trọng lượng lớn.

# PHỤ LỤC E. NHẬT KÝ NHÓM VÀ MINH CHỨNG

Mẫu nhật ký tuần: Ngày/tuần | Thành viên | Ticket/commit | Phạm vi | Đường dẫn minh chứng | Phát hiện | Test đã chạy | Kết quả | Vấn đề chưa xử lý | Kế hoạch tuần tới. Những mục chưa có bằng chứng trong repository/nhật ký hiện có phải để 'chưa cung cấp', không gán thành quả cho một thành viên.

Phân công đề xuất (chờ nhóm xác nhận): A — PDF classification/ingestion và bộ dữ liệu; B — formula/LaTeX/OMML và đo accuracy; C — layout/tables/web UI và thử nghiệm E2E. Cả ba cùng duyệt bảng kết quả và chịu trách nhiệm đối chiếu cuối cùng với nguồn PDF. Không xem đây là nhật ký đã diễn ra.