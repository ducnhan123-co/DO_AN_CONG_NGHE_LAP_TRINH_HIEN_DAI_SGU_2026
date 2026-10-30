// Địa chỉ backend. Trang do chính server phục vụ (http/https, cổng nào cũng được) thì gọi cùng nguồn gốc.
// Chỉ khi mở file HTML trực tiếp bằng file:// mới cần trỏ về backend mặc định.
window.APP_API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
