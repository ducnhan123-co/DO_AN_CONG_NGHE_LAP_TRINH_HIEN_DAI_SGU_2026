"""Backend FastAPI cho ứng dụng chat với tài liệu PDF toán, theo mô hình MVC.

- controllers/ : nhận request, gọi model, trả response
- models/      : nghiệp vụ, CSDL, pipeline xử lý PDF
- views/       : schema Pydantic định dạng dữ liệu vào/ra
- core/        : cấu hình, lỗi chuẩn, mô hình ngôn ngữ dùng chung
"""