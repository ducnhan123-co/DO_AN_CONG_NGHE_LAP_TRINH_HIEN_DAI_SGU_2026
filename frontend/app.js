const $ = (id) => document.getElementById(id);
const STATUS = { queued: "Đang chờ", running: "Đang chạy", done: "Xong", failed: "Lỗi" };
let current = null;
let timer = null;

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

function badge(el, status) {
  el.textContent = STATUS[status] || status;
  el.className = "badge " + status;
}

async function loadJobs() {
  const jobs = await api("/api/jobs");
  const ul = $("jobs");
  ul.replaceChildren(...jobs.map((j) => {
    const li = document.createElement("li");
    li.className = j.id === current ? "active" : "";
    const name = document.createElement("span");
    name.textContent = j.name;
    const meta = document.createElement("small");
    meta.textContent = `${j.tier} · ${new Date(j.created * 1000).toLocaleString("vi-VN")}`;
    const b = document.createElement("span");
    badge(b, j.status);
    li.append(name, meta, b);
    li.onclick = () => select(j.id);
    return li;
  }));
  if (!jobs.length) ul.innerHTML = "<li class='empty'>Chưa có lượt chạy nào.</li>";
}

function renderAudit(a) {
  const box = $("dAudit");
  if (!a) return box.replaceChildren();
  const d = a.docx || {};
  const stats = [
    ["Equation trong DOCX", d.equations ?? "–"],
    ["Đoạn còn LaTeX thô", d.raw_latex_paragraphs ?? "–"],
    ["Trang MinerU bỏ khối", a.dropped_pages.length],
    ["Chỗ nhảy số bài/ý", a.numbering_gaps.length],
  ];
  box.replaceChildren(...stats.map(([k, v]) => {
    const div = document.createElement("div");
    div.innerHTML = "<b></b><span></span>";
    div.firstChild.textContent = v;
    div.lastChild.textContent = k;
    return div;
  }));
}

async function refresh() {
  if (!current) return;
  const j = await api(`/api/jobs/${current}`);
  $("detail").hidden = false;
  $("dName").textContent = j.name;
  badge($("dStatus"), j.status);
  $("dDownload").hidden = j.status !== "done";
  $("dDownload").href = `/api/jobs/${j.id}/docx`;
  renderAudit(j.audit);
  const log = $("dLog");
  log.textContent = j.error || j.log || "(chưa có log)";
  log.scrollTop = log.scrollHeight;
  clearTimeout(timer);
  if (j.status === "queued" || j.status === "running") timer = setTimeout(tick, 2000);
}

async function tick() {
  await Promise.all([refresh(), loadJobs()]).catch(console.error);
}

function select(id) {
  current = id;
  tick();
}

$("file").onchange = () => {
  const f = $("file").files[0];
  $("fileLabel").textContent = f ? f.name : "Chọn hoặc kéo thả PDF";
};
["dragover", "dragleave", "drop"].forEach((ev) =>
  $("drop").addEventListener(ev, () => $("drop").classList.toggle("over", ev === "dragover")));

$("form").onsubmit = async (e) => {
  e.preventDefault();
  $("error").textContent = "";
  $("submit").disabled = true;
  const fd = new FormData();
  fd.append("file", $("file").files[0]);
  fd.append("tier", $("tier").value);
  fd.append("workers", $("workers").value);
  try {
    const job = await api("/api/jobs", { method: "POST", body: fd });
    $("form").reset();
    $("fileLabel").textContent = "Chọn hoặc kéo thả PDF";
    select(job.id);
  } catch (err) {
    $("error").textContent = err.message;
  } finally {
    $("submit").disabled = false;
  }
};

loadJobs().catch((err) => ($("error").textContent = "Không kết nối được backend: " + err.message));
