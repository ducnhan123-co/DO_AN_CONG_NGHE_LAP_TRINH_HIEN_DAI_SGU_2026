/* Dùng chung cho index.html và reader.html: gọi API, định dạng, dải trang, các bước. Không phụ thuộc thư viện ngoài. */
(function () {
  const BASE = ((window.APP_API_BASE || "").replace(/\/$/, "")) + "/api";
  const LABEL = {
    queued: "Đang chờ", parsing: "Đang dịch bằng MinerU", merging: "Đang ghép các phần", preparing: "Đang chuẩn hóa công thức",
    building: "Đang dựng file Word", validating: "Đang kiểm tra file Word", done: "Xong", failed: "Lỗi", cancelled: "Đã hủy",
  };
  const ACTIVE = ["queued", "parsing", "merging", "preparing", "building", "validating"];
  const STEPS = ["Dịch", "Ghép", "Chuẩn hóa", "Dựng Word", "Kiểm tra"];
  const STEP_OF = { parsing: 0, merging: 1, preparing: 2, building: 3, validating: 4 };
  const STEP_OF_ERROR = { MERGE_FAILED: 1, PREPARE_FAILED: 2, EMPTY_MARKDOWN: 2, PANDOC_FAILED: 3, PANDOC_NOT_FOUND: 3, DOCX_BUILD_FAILED: 3, DOCX_INVALID: 4 };

  class ApiError extends Error {
    constructor(status, code, message) { super(message); this.status = status; this.code = code; }
  }

  function clientId() {
    try {
      let v = localStorage.getItem("pdf2docx_client_id");
      if (!v) {
        const raw = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2));
        v = "c" + raw.replace(/[^A-Za-z0-9_-]/g, "");
        localStorage.setItem("pdf2docx_client_id", v);
      }
      return v;
    } catch (e) { return "c" + Math.random().toString(36).slice(2, 12); }
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({ "X-Client-Id": clientId() }, opts.headers || {});
    let res;
    try { res = await fetch(BASE + path, Object.assign({}, opts, { headers })); }
    catch (e) { throw new ApiError(0, "OFFLINE", "Không kết nối được máy chủ. Server đã chạy chưa?"); }
    if (res.status === 204) return null;
    let data = null;
    try { data = await res.json(); } catch (e) { /* không phải JSON */ }
    if (!res.ok) throw new ApiError(res.status, (data && data.error && data.error.code) || "HTTP_ERROR", (data && data.error && data.error.message) || ("Lỗi " + res.status));
    return data;
  }

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtBytes = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1).replace(".", ",") + " MB";
  function fmtDur(s) {
    if (s == null) return "–";
    s = Math.max(0, Math.round(s));
    return s < 3600 ? Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0") : Math.floor(s / 3600) + ":" + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }
  const fmtTime = (t) => t ? new Date(t * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit", day: "2-digit", month: "2-digit" }) : "–";
  const isActive = (st) => ACTIVE.indexOf(st) >= 0;

  function badgeClass(st) {
    return st === "done" ? "done" : st === "failed" ? "bad" : st === "cancelled" || st === "queued" ? "idle" : "run";
  }

  /* 5 bước của pipeline; khi lỗi thì đánh dấu đúng bước lỗi theo mã lỗi. */
  function stepsHTML(doc) {
    let cur = STEP_OF[doc.status];
    const failed = doc.status === "failed";
    if (failed) cur = doc.error && STEP_OF_ERROR[doc.error.code] != null ? STEP_OF_ERROR[doc.error.code] : 0;
    return '<ol class="steps' + (doc.status === "done" ? " ok" : "") + '" aria-label="Các bước xử lý">' + STEPS.map((name, i) => {
      let cls = "";
      if (doc.status === "done") cls = "done";
      else if (cur != null && i < cur) cls = "done";
      else if (cur != null && i === cur) cls = failed ? "fail" : "active";
      return '<li class="' + cls + '">' + esc(name) + "</li>";
    }).join("") + "</ol>";
  }

  function progressHTML(doc) {
    const value = Math.max(0, Math.min(100, Number(doc.progress) || 0));
    const label = doc.status === "done" ? "Hoàn tất" : "Tiến độ";
    return '<div class="progress-wrap' + (isActive(doc.status) ? " active" : "") + '"><div class="progress-label"><span>' + label + '</span><span class="num">' +
      Math.floor(value) + '%</span></div><div class="progress-track" role="progressbar" aria-label="' + label +
      '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + value + '"><i style="width:' + value +
      '%"></i></div></div>';
  }

  function whatText(doc) {
    if (doc.status === "parsing") {
      const sh = doc.shards || [], run = sh.filter((s) => s.status === "running");
      if (sh.length > 1 && run.length) return "Dịch phần " + run.map((s) => s.index).join(", ") + "/" + sh.length +
        " (trang " + run.map((s) => s.page_from + "–" + s.page_to + ", ~" + Math.floor(s.progress || 0) + "%").join(", ") + ")";
      if (sh.length > 1) {
        const done = sh.filter((s) => s.status === "done").length;
        const waiting = sh.length - done;
        return waiting ? "Đã xong " + done + "/" + sh.length + " phần · " + waiting + " phần đang chờ" :
          "Đã xong " + done + "/" + sh.length + " phần";
      }
    }
    if (doc.status === "queued") return "Đang chờ tới lượt";
    if (doc.status === "done") return doc.cache_hit ? "Dùng lại kết quả của file giống hệt đã chuyển" : "Đã chuyển xong";
    return LABEL[doc.status] || doc.status;
  }

  let toastBox;
  function toast(msg, bad) {
    if (!toastBox) { toastBox = document.createElement("div"); toastBox.className = "toasts"; toastBox.setAttribute("aria-live", "polite"); document.body.appendChild(toastBox); }
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.textContent = msg;
    toastBox.appendChild(el);
    setTimeout(() => el.remove(), bad ? 7000 : 3800);
  }

  window.App = { BASE, LABEL, ACTIVE, ApiError, api, clientId, esc, fmtBytes, fmtDur, fmtTime, isActive, badgeClass, stepsHTML, progressHTML, whatText, toast };
})();
