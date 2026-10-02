"""E2E thủ công (cần 3 server đang chạy: BE :8001, FE :8080, Library :8002 + Ollama).

    python3 tests/e2e_library.py

Kiểm: upload -> chat -> reload còn chat -> đổi tài liệu cũ còn chat -> lịch sử DOCX ->
xóa phiên / đổi tên / xóa tài liệu -> tắt 8002 chat vẫn chạy. Tạo PDF mẫu bằng PyMuPDF trong thư mục tạm.
"""
import sys
import tempfile
import time
from pathlib import Path

import fitz
from playwright.sync_api import sync_playwright

FE = "http://127.0.0.1:8080"
TMP = Path(tempfile.mkdtemp())


def make_pdf(name: str, text: str) -> Path:
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"{text} trang {i + 1}. " * 6, fontsize=11)
    path = TMP / name
    doc.save(path)
    return path


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def wait_ready(pg, timeout=60):
    for _ in range(timeout):
        if "chunks" in pg.inner_text("#docMeta"):
            return
        pg.wait_for_timeout(1000)
    check(False, "tài liệu sẵn sàng chat")


def ask(pg, question):
    before = pg.locator("#chatScroll .msg-in").count()
    pg.fill("#chatInput", question)
    pg.click("#sendBtn")
    pg.wait_for_function("n => document.querySelectorAll('#chatScroll .msg-in').length >= n + 2", arg=before, timeout=120000)
    pg.wait_for_function("() => !document.querySelector('#chatScroll .typing')", timeout=180000)
    pg.wait_for_timeout(800)  # chờ POST lưu tin nhắn


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("PAGEERR", e))
    pdf_a, pdf_b = make_pdf("tai-lieu-A.pdf", "Đạo hàm của hàm số"), make_pdf("tai-lieu-B.pdf", "Tích phân xác định")
    dialogs = []
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept("Toán A3 đổi tên") if d.type == "prompt" else d.accept()))

    # 1. upload A -> reader, chọn model nhanh, chat
    pg.goto(f"{FE}/index.html")
    pg.evaluate("openUpload()")
    pg.set_input_files("#fileInput", str(pdf_a))
    pg.wait_for_url("**/reader.html?doc_id=*", timeout=20000)
    doc_a = pg.url.split("doc_id=")[1]
    wait_ready(pg)
    pg.select_option("#modelSel", "qwen2.5:1.5b")
    ask(pg, "Tài liệu này nói về gì?")
    check(pg.locator("#sessionList button").count() >= 1, "phiên chat xuất hiện ở sidebar sau lượt hỏi đầu")

    # 2. reload -> chat còn
    pg.reload()
    pg.wait_for_function("() => document.querySelectorAll('#chatScroll .msg-in').length >= 2", timeout=20000)
    check("Tài liệu này nói về gì?" in pg.inner_text("#chatScroll"), "reload trang: câu hỏi vẫn còn")

    # 3. upload B, rồi quay lại A từ 'Tài liệu gần đây' -> chat A còn
    pg.goto(f"{FE}/index.html")
    pg.evaluate("openUpload()")
    pg.set_input_files("#fileInput", str(pdf_b))
    pg.wait_for_url("**/reader.html?doc_id=*", timeout=20000)
    wait_ready(pg)
    check("Tài liệu này nói về gì?" not in pg.inner_text("#chatScroll"), "tài liệu B không lẫn chat của A")
    pg.locator("#recentDocs button", has_text="tai-lieu-A.pdf").first.click()
    pg.wait_for_function("() => document.getElementById('docTitle').textContent.includes('tai-lieu-A')", timeout=20000)
    pg.wait_for_function("() => document.querySelectorAll('#chatScroll .msg-in').length >= 2", timeout=20000)
    check("Tài liệu này nói về gì?" in pg.inner_text("#chatScroll"), "đổi sang tài liệu cũ: chat được nạp lại")
    pg.wait_for_timeout(2000)
    check(pg.locator("#viewer .page").count() > 0, "khung PDF của tài liệu cũ có trang hiển thị")
    pg.screenshot(path=str(TMP / "reader-A.png"))

    # 4. lịch sử DOCX (nếu BE đã tạo xong)
    for _ in range(40):
        if pg.evaluate("!document.getElementById('btnDocx').classList.contains('pointer-events-none')"):
            break
        pg.wait_for_timeout(1000)
    pg.click("#btnHist")
    pg.wait_for_function("() => !document.getElementById('histBody').textContent.includes('Đang tải')", timeout=10000)
    hist = pg.inner_text("#histBody")
    print("HIST:", hist.replace("\n", " | ")[:300])
    check("nhật ký hoạt động" in hist.lower() and "Thêm tài liệu" in hist, "hộp Lịch sử hiện nhật ký")  # tiêu đề CSS uppercase
    print("INFO DOCX trong lịch sử:", "v1" in hist)
    pg.keyboard.press("Escape")

    # 5. xóa phiên qua menu ⋯
    pg.locator("#sessionList button[title='Tùy chọn']").first.click()
    pg.get_by_text("Xóa phiên").click()
    pg.wait_for_function("() => document.querySelectorAll('#sessionList button').length === 0", timeout=10000)
    check(True, "xóa phiên: danh sách phiên trống")

    # 6. thư viện: đổi tên + xóa tài liệu
    pg.goto(f"{FE}/index.html")
    pg.wait_for_selector("#grid article", timeout=10000)
    check(pg.locator("#grid article").count() == 2, "thư viện hiện 2 tài liệu từ server")
    pg.locator("#grid article", has_text="tai-lieu-A").locator("button[title='Tùy chọn']").click()
    pg.get_by_text("Đổi tên").click()
    pg.wait_for_selector("#grid article h3:has-text('Toán A3 đổi tên')", timeout=10000)
    check(True, "đổi tên tài liệu hiển thị trên thẻ")
    pg.locator("#grid article", has_text="Toán A3").locator("button[title='Tùy chọn']").click()
    pg.get_by_text("Xóa tài liệu + PDF").click()
    pg.wait_for_function("() => document.querySelectorAll('#grid article').length === 1", timeout=10000)
    check("PDF trên server chưa xóa được" in pg.inner_text("#toast") or "Đã xóa" in pg.inner_text("#toast"), "xóa tài liệu có thông báo về PDF")

    # 7. 8002 tắt -> chat vẫn chạy
    ctx.route("**://127.0.0.1:8002/**", lambda route: route.abort())
    pg.goto(f"{FE}/index.html")
    pg.evaluate("openUpload()")
    pg.set_input_files("#fileInput", str(make_pdf("tai-lieu-C.pdf", "Chuỗi số hội tụ")))
    pg.wait_for_url("**/reader.html?doc_id=*", timeout=20000)
    wait_ready(pg)
    pg.select_option("#modelSel", "qwen2.5:1.5b")
    ask(pg, "Hỏi khi thư viện tắt")
    check("Hỏi khi thư viện tắt" in pg.inner_text("#chatScroll"), "8002 tắt: chat vẫn chạy bằng BE")
    browser.close()
print("E2E OK")
