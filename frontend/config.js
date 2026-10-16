// Địa chỉ backend. Mở giao diện qua chính server (http://127.0.0.1:8000/) thì để rỗng -> cùng nguồn gốc.
// Mở file HTML trực tiếp hoặc dùng live-server cổng khác thì trỏ về backend.
window.APP_API_BASE = (location.protocol === "file:" || (location.port && location.port !== "8000"))
  ? "http://127.0.0.1:8000" : "";
