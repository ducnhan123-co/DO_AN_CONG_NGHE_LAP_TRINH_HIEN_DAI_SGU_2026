"""Chạy backend:  python run.py     (mặc định http://127.0.0.1:8000 — mở thẳng giao diện ở địa chỉ này)"""
import uvicorn

from app.core.config import load_settings

if __name__ == "__main__":
    s = load_settings()
    # 1 process duy nhất: hàng đợi + worker nằm trong process này (đừng dùng --workers > 1)
    uvicorn.run("app.main:create_app", factory=True, host=s.host, port=s.port, log_level="info")
