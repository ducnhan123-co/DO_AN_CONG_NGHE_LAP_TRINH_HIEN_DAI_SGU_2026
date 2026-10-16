// Kiểm thử giao diện bằng jsdom trên server THẬT (Pandoc thật, mineru-kit giả). Chạy qua run_ui_test.sh.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const BASE = "http://127.0.0.1:8000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const errors = [];
const vc = new VirtualConsole();
let navAttempts = 0;
vc.on("jsdomError", (e) => { if (/navigation to another Document/.test(e.message)) { navAttempts++; return; } if (!/fonts\.g|Could not load link|stylesheet/i.test(e.message)) errors.push("jsdomError: " + e.message.slice(0, 200)); });
vc.on("error", (e) => errors.push("console.error: " + String(e).slice(0, 200)));

async function open(path, extra) {
  const dom = await JSDOM.fromURL(BASE + path, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = (u, o) => fetch(new URL(u, w.location.href), o);
      if (global.__cid) w.localStorage.setItem("pdf2docx_client_id", global.__cid);   // trình duyệt thật dùng chung localStorage giữa các trang
      w.confirm = () => true; w.prompt = () => "Giải tích 1 (đã đổi tên)";
      if (extra) extra(w);
    } });
  return dom;
}
const text = (el) => el.textContent.replace(/\s+/g, " ").trim();
let failed = 0;
function check(name, ok, info) { console.log((ok ? "PASS " : "FAIL ") + name + (info ? "  -> " + info : "")); if (!ok) failed++; }
async function waitFor(fn, ms = 60000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); } return null; }

(async () => {
  const dom = await open("/index.html");
  const w = dom.window, d = w.document;
  global.__cid = await waitFor(() => w.localStorage.getItem("pdf2docx_client_id"), 8000);   // app.js tạo mã client ở lần gọi API đầu tiên
  await waitFor(() => text(d.getElementById("list")).includes("Chưa có tài liệu"), 8000);
  check("trang chủ: trạng thái rỗng", text(d.getElementById("list")).includes("Chưa có tài liệu nào"));
  check("hiển thị ô thả file + chỉ báo slot", !!d.getElementById("drop") && (await waitFor(() => d.querySelectorAll("#slots .dot").length >= 3, 6000)) !== null,
        d.querySelectorAll("#slots .dot").length + " chấm");

  // upload 2 PDF qua đúng input của giao diện
  const input = d.getElementById("file");
  const mk = (p, name) => new w.File([fs.readFileSync(p)], name, { type: "application/pdf" });
  Object.defineProperty(input, "files", { value: [mk(process.env.PDF_A, "Giai tich A3.pdf"), mk(process.env.PDF_B, "Dai so.pdf"), new w.File(["x"], "ghichu.txt", { type: "text/plain" })], configurable: true });
  input.dispatchEvent(new w.Event("change", { bubbles: true }));

  const rows = await waitFor(() => { const r = d.querySelectorAll("#list .row"); return r.length === 2 ? r : null; }, 15000);
  check("upload nhiều file: 2 dòng xuất hiện", !!rows, rows && Array.from(rows).map((r) => text(r.querySelector(".name"))).join(" | "));
  check("file không phải PDF bị báo ngay ở trình duyệt", text(d.body).includes("ghichu.txt: không phải file PDF"));
  check("tab đếm đúng", text(d.getElementById("tabs")).includes("Tất cả2"));

  // đang chạy: dải trang + các bước + slot
  const running = await waitFor(() => { const r = Array.from(d.querySelectorAll("#list .row")).find((x) => /Đang dịch bằng MinerU/.test(text(x))); return r || null; }, 15000);
  check("dòng đang chạy hiện trạng thái 'Đang dịch bằng MinerU'", !!running);
  if (running) {
    const cells = running.querySelectorAll(".ribbon i");
    check("dải trang có số ô = số trang (hoặc tối đa 96)", cells.length === 46 || cells.length === 12, cells.length + " ô");
    check("có ô 'đang chạy' (bút dạ vàng)", running.querySelectorAll(".ribbon i.c-run").length > 0);
    check("hiển thị 5 bước pipeline", running.querySelectorAll(".steps li").length === 5);
    check("có nút Hủy khi đang chạy", !!running.querySelector('[data-act="cancel"]'));
  }
  const slotsBusy = await waitFor(() => d.querySelectorAll("#slots .dot.on").length >= 1, 8000);
  check("chỉ báo slot sáng khi MinerU chạy", !!slotsBusy, text(d.getElementById("slots")));

  // chờ xong
  const done = await waitFor(() => { const r = Array.from(d.querySelectorAll("#list .row")); return r.length === 2 && r.every((x) => x.querySelector("a.btn.primary")) ? r : null; }, 90000);
  check("cả 2 file xong, có nút 'Tải Word'", !!done);
  let docIds = [];
  if (done) {
    docIds = Array.from(done).map((r) => r.dataset.id);
    const big = done.find((r) => /Giai tich/.test(text(r)));
    check("file 46 trang: ô đã xong màu xanh lá, badge 'Xong'", big.querySelectorAll(".ribbon.ok i.c-done").length === 46 && /Xong/.test(text(big.querySelector(".badge"))));
    check("hiển thị số phần song song", /2 phần song song/.test(text(big)));
    const href = big.querySelector("a.btn.primary").getAttribute("href");
    const r = await fetch(new URL(href, BASE));
    check("link 'Tải Word' tải được file DOCX", r.status === 200 && (r.headers.get("content-type") || "").includes("wordprocessingml"), href);
  }

  // tìm kiếm + lọc
  const q = d.getElementById("q");
  const search = async (v) => { q.value = v; q.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(100); return Array.from(d.querySelectorAll("#list .row")).map((r) => text(r.querySelector(".name"))); };
  let r1 = await search("dai so"), r2 = await search("GIẢI TÍCH"), r3 = await search("đại số"), r4 = await search("khong co");
  check("tìm kiếm không phân biệt hoa/thường và dấu", r1.length === 1 && /Dai so/.test(r1[0]) && r2.length === 1 && /Giai tich/.test(r2[0]) && r3.length === 1 && r4.length === 0,
        JSON.stringify([r1, r2, r3, r4.length]));
  q.value = ""; q.dispatchEvent(new w.Event("input", { bubbles: true }));
  d.querySelector('#tabs [data-f="failed"]').click(); await sleep(100);
  check("tab 'Lỗi / hủy' không có dòng nào -> trạng thái rỗng", text(d.getElementById("list")).includes("Không có tài liệu khớp"));
  d.querySelector('#tabs [data-f="all"]').click(); await sleep(100);

  // đổi tên
  const bigRow = done && done.find((r) => /Giai tich/.test(text(r))), smallRow = done && done.find((r) => /Dai so/.test(text(r)));
  const bigId = bigRow && bigRow.dataset.id, smallId = smallRow && smallRow.dataset.id;
  if (docIds.length) {
    d.querySelector('[data-act="rename"][data-id="' + bigId + '"]').click();
    const renamed = await waitFor(() => /Giải tích 1 \(đã đổi tên\)/.test(text(d.getElementById("list"))), 8000);
    check("đổi tên hiển thị ngay", !!renamed);
  }

  // trang đọc
  if (docIds.length) {
    const target = (await (await fetch(BASE + "/api/documents/" + bigId)).json());
    const rd = await open("/reader.html?doc_id=" + bigId);
    const rdd = rd.window.document;
    const titled = await waitFor(() => rdd.getElementById("title").textContent !== "Đang tải…", 8000);
    check("reader: tiêu đề = tên tài liệu", !!titled, rdd.getElementById("title").textContent);
    const ifr = await waitFor(() => rdd.querySelector("#viewer iframe"), 5000);
    check("reader: nhúng PDF gốc qua API", !!ifr && ifr.getAttribute("src").includes("/documents/" + bigId + "/pdf"), ifr && ifr.getAttribute("src"));
    const panel = await waitFor(() => text(rdd.getElementById("panel")).includes("Chi tiết từng bước") ? rdd.getElementById("panel") : null, 8000);
    const ptxt = panel ? text(panel) : "";
    check("reader: có 100% và dải trang", /100%/.test(ptxt) && rdd.querySelectorAll("#panel .ribbon i").length > 0);
    check("reader: timeline có các bước ghép, chuẩn hóa, dựng Word, kiểm tra", ["Dịch bằng MinerU", "Chuẩn hóa công thức", "Dựng file Word", "Kiểm tra file Word"].every((s) => ptxt.includes(s)));
    if (target.shards.length > 1) check("reader: liệt kê từng phần với slot và thời gian", /Phần 1\/2 · trang 1–23 · slot (chính|phụ)/.test(ptxt) && /Phần 2\/2/.test(ptxt), (ptxt.match(/Phần 1\/2[^P]*/) || [""])[0].slice(0, 90));
    check("reader: hiện số công thức thành Equation", /\d+\/\d+ công thức thành Equation/.test(ptxt), (ptxt.match(/\d+\/\d+ công thức thành Equation[^K]{0,40}/) || [""])[0]);
    await waitFor(() => rdd.querySelectorAll("#pick option").length >= 2, 4000);
    check("reader: có nút Tải Word và danh sách chuyển tài liệu", !!rdd.querySelector("#topActions a.btn.primary") && rdd.querySelectorAll("#pick option").length >= 2,
          "nút Tải Word: " + rdd.querySelectorAll("#topActions a.btn.primary").length + ", tuỳ chọn chuyển tài liệu: " + rdd.querySelectorAll("#pick option").length + ", client id: " + (rd.window.localStorage.getItem("pdf2docx_client_id") === global.__cid));
    rd.window.close();

    const bad = await open("/reader.html?doc_id=khongtontai01");
    await waitFor(() => bad.window.document.getElementById("title").textContent.includes("Không tìm thấy"), 8000);
    check("reader: tài liệu không tồn tại -> thông báo rõ", bad.window.document.getElementById("title").textContent.includes("Không tìm thấy"));
    bad.window.close();
    const before = navAttempts;
    const noid = await open("/reader.html");
    await sleep(400);
    check("reader: thiếu doc_id -> cố chuyển về trang chủ (jsdom không thực hiện điều hướng)", navAttempts === before + 1, "lần điều hướng: " + (navAttempts - before));
    noid.window.close();
  }

  // xóa
  if (docIds.length) {
    d.querySelector('[data-act="delete"][data-id="' + smallId + '"]').click();
    const gone = await waitFor(() => d.querySelectorAll("#list .row").length === 1, 8000);
    check("xóa tài liệu: dòng biến mất", !!gone);
  }
  check("không có lỗi JavaScript nào trong console", errors.length === 0, errors.slice(0, 3).join(" || "));
  console.log(failed ? `\n${failed} KIỂM TRA THẤT BẠI` : "\nTẤT CẢ KIỂM TRA GIAO DIỆN ĐẠT");
  w.close(); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("LỖI TEST:", e); process.exit(2); });
