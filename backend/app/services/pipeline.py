"""Pipeline xử lý 1 PDF — chuyển thể từ rag_toan/main.py thành các bước theo dõi/hủy/chạy lại được.

main.py (CLI)                                   Pipeline.run (backend)                 status    %
-------------------------------------------     ------------------------------------   --------  -------
0.  prepare_run_dir  (runs/<ten>_<id>)          documents/<id>/ (+ input/<id>.pdf)     parsing    2
0b. plan_strips + build_strips_pdf              như cũ (PDF nhiều cột -> dải cột)      parsing
1.  run_mineru_parallel                         MineruRunner (Popen, hủy được)         parsing   2-70
    (ghép các phần)                             merge_parts                            merging   70-75
2.  fix_legacy_tex_bf -> prepare_work_md        như cũ -> documents/<id>/work.md       preparing 75-82
2b. md_to_docx + cột/khung                      như cũ -> docx_output/<id>.docx        building  82-92
    (kiểm tra Word)                             validate_docx                          validating 92-97
3.  structured + chunks + validation            như cũ, KHÔNG làm hỏng kết quả Word    validating 97-99
4.  LlamaIndex (tùy chọn)                       rag_service.build_index (RAG_INDEX=1)  validating
5.  Qwen (tùy chọn)                             không đưa vào luồng tải tài liệu

Chạy lại (retry/khởi động lại server) là "resume": phần MinerU đã .done và kết quả đã ghép được bỏ qua.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..core.config import Settings
from ..core.errors import Cancelled, PipelineError
from ..core.log_router import capture_to, log_line
from ..models.document_repository import DocumentRepository
from ..models.entities import (BUILDING, CANCELLED, DONE, FAILED, MERGING, PARSING, PREPARING, VALIDATING,
                               Document)
from .docx_validator import validate_docx
from .engine import Engine
from .mineru_runner import MineruRunner
from .storage import Storage

# stage -> mã lỗi mặc định khi gặp ngoại lệ không lường trước (frontend dùng mã này để tô đúng bước)
_STAGE_ERROR = {"parse": "MINERU_FAILED", "merge": "MERGE_FAILED", "prepare": "PREPARE_FAILED",
                "build": "DOCX_BUILD_FAILED", "validate": "DOCX_INVALID"}


class Pipeline:
    def __init__(self, settings: Settings, repo: DocumentRepository, storage: Storage, engine: Engine,
                 runner: MineruRunner):
        self.s, self.repo, self.storage, self.engine, self.runner = settings, repo, storage, engine, runner
        self._spp_lock = threading.Lock()

    # ------------------------------------------------------------------ vào/ra
    def run(self, doc: Document, cancel: threading.Event, force: bool = False) -> None:
        """Chạy trọn pipeline; luôn để lại trạng thái cuối (done / failed / cancelled) trong DB."""
        run = _Run(self, doc.id, cancel)
        self.storage.make_run_dirs(doc.id)
        with capture_to(self.storage.pipeline_log(doc.id)):
            log_line(f"===== BẮT ĐẦU {doc.id} | {doc.filename} | {doc.num_pages} trang | force={force} =====")
            t0 = time.time()
            try:
                self._run(doc, run, force)
                log_line(f"===== XONG sau {time.time() - t0:.0f}s =====")
            except Cancelled:
                run.abort(CANCELLED)
                log_line("===== ĐÃ HỦY =====")
            except PipelineError as ex:
                run.abort(FAILED, ex.code, ex.message)
                log_line(f"===== LỖI {ex.code}: {ex.message} =====")
            except Exception as ex:                                   # noqa: BLE001
                import traceback
                log_line(traceback.format_exc())
                code = _STAGE_ERROR.get(run.current or "", "PIPELINE_ERROR")
                run.abort(FAILED, code, f"{type(ex).__name__}: {ex}")
                log_line(f"===== LỖI {code}: {ex} =====")

    # ------------------------------------------------------------------ các bước
    def _run(self, doc: Document, run: "_Run", force: bool) -> None:
        s, st, repo = self.s, self.storage, self.repo
        E = self.engine.load()                                         # ENGINE_NOT_FOUND nếu thiếu rag_toan
        if not self.engine.pandoc_found:                               # báo sớm, đừng đợi MinerU chạy xong mới lỗi
            raise PipelineError("PANDOC_NOT_FOUND", "Không tìm thấy Pandoc (chưa cài hoặc không có trong PATH).")
        doc_id = doc.id
        pdf_path = st.input_pdf(doc_id)
        if not pdf_path.is_file():
            raise PipelineError("INPUT_MISSING", f"Mất file PDF gốc: {pdf_path}")
        run_dir = st.run_dir(doc_id)
        mineru_dir = run_dir / "mineru"
        merged_mark = mineru_dir / ".merged"
        repo.update(doc_id, tier=s.mineru_tier)

        if force:                                                       # như --force của main.py
            shutil.rmtree(mineru_dir, ignore_errors=True)
            shutil.rmtree(run_dir / "mineru_parts", ignore_errors=True)
            repo.update(doc_id, shards=[])

        # 0b. PDF "tờ khung nhiều cột" -> tách dải cột (không phải PDF đó thì plan=None, mọi thứ chạy như cũ)
        plan = None
        if not (s.no_split or s.no_columns):
            plan = self._safe("plan_strips", lambda: E.column_split.plan_strips(pdf_path))
        need_parse = not merged_mark.exists()

        # ------------------------------------------------------------ 1. MinerU
        run.begin("parse", PARSING, 2)
        part_outs: List[Path] = []
        ranges: List[tuple] = []
        total_pages = doc.num_pages
        if need_parse:
            mineru_pdf = pdf_path
            if plan:
                mineru_pdf = E.column_split.build_strips_pdf(pdf_path, run_dir / f"{doc_id}__strips.pdf", plan)
                E.column_split.save_plan(plan, run_dir / "strips_plan.json")
                log_line(f"[split] {len(plan['strips'])} dải cột từ {plan['pages']} trang -> MinerU đọc {mineru_pdf.name}")
            from pypdf import PdfReader
            total_pages = len(PdfReader(str(mineru_pdf)).pages)
            ranges = self.runner.plan_ranges(total_pages)
            shards = [{"index": k + 1, "page_from": a + 1, "page_to": b, "status": "pending", "progress": 0.0,
                       "elapsed_s": None, "peak_ram_gb": None, "error": None} for k, (a, b) in enumerate(ranges)]
            lock = threading.Lock()

            def on_update() -> None:
                with lock:
                    avg = sum(x["progress"] for x in shards) / max(1, len(shards))
                    repo.update(doc_id, shards=shards, progress=round(2 + 68 * avg / 100, 1))

            on_update()
            log_line(f"[MinerU] {total_pages} trang -> {len(ranges)} tiến trình: "
                     + ", ".join(f"{a + 1}-{b}" for a, b in ranges))
            part_outs = self.runner.run(doc_id, mineru_pdf, run_dir, ranges, shards, on_update, run.cancel,
                                        self._get_spp(), self._record_spp)
            run.end("parse", {"pages": total_pages, "parts": len(ranges)})
        else:
            log_line("[MinerU] Đã có kết quả đã ghép cho PDF này, bỏ qua chạy lại (retry?force=true để chạy lại)")
            run.end("parse", {"skipped": True})
        run.check()

        # ------------------------------------------------------------ 1b. ghép
        run.begin("merge", MERGING, 70)
        if need_parse:
            try:
                shutil.rmtree(mineru_dir, ignore_errors=True)           # bỏ kết quả ghép dở dang (nếu có)
                md_out, cl_out = E.parallel.merge_parts(part_outs, ranges, mineru_dir, doc_id)
                (run_dir / "mineru" / "parallel_info.json").write_text(
                    json.dumps({"total_pages": total_pages, "ranges_1based": [[a + 1, b] for a, b in ranges]},
                               ensure_ascii=False, indent=2), encoding="utf-8")
                merged_mark.write_text("ok", encoding="utf-8")
            except Exception as ex:                                     # noqa: BLE001
                raise PipelineError("MERGE_FAILED", f"Ghép kết quả MinerU lỗi: {ex}") from ex
        md_path, _json_files, _image_files = E.run_mineru.find_mineru_outputs(mineru_dir)
        content_list_path = E.run_mineru.find_content_list(mineru_dir)
        run.end("merge", {"parts": len(ranges) or None})
        run.check()
        if plan and not content_list_path:
            log_line("[split] MinerU không trả content_list.json -> bỏ chế độ tách dải, dùng Markdown như cũ.")
            plan = None

        # ------------------------------------------------------------ 2. chuẩn hóa -> work.md
        run.begin("prepare", PREPARING, 75)
        markdown_text = E.build_docx.fix_legacy_tex_bf(md_path.read_text(encoding="utf-8", errors="ignore"))
        if not markdown_text.strip():
            raise PipelineError("EMPTY_MARKDOWN", "MinerU không trích được chữ nào từ PDF này (PDF scan chất lượng thấp?).")
        layout = None
        if plan:                       # đã có thứ tự cột chính xác -> không cần OCR dò cột
            strips_raw = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
            docx_md = E.column_split.content_list_to_docx_md(strips_raw, plan)
        else:
            if not s.no_columns:
                layout = self._safe("layout_of", lambda: E.columns.layout_of(pdf_path, lang=s.ocr_lang))
            docx_md = markdown_text
            if layout:
                docx_md = E.columns.insert_column_breaks(E.columns.drop_ocr_details(markdown_text), layout)
        work_md = run_dir / "work.md"
        E.build_docx.prepare_work_md(docx_md, md_path, work_md)
        run.end("prepare", {"columns": (plan or {}).get("ncols") or (layout or {}).get("n_cols") or 1})
        run.check()

        # ------------------------------------------------------------ 2b. dựng Word (file tạm, đổi tên nguyên tử khi hợp lệ)
        run.begin("build", BUILDING, 82)
        tmp_docx = st.docx_building_path(doc_id)
        final_docx = st.docx_path(doc_id)
        try:
            E.build_docx.md_to_docx(work_md, tmp_docx, md_path.parent)
            body_pt = s.col_font_pt or None
            if layout:
                E.columns.apply_section_columns(tmp_docx, layout["n_cols"], layout["page_pt"], body_pt=body_pt)
            frame = None if (s.no_frame or s.no_columns) else self._safe(
                "detect_frame_layout", lambda: E.frame_layout.detect_frame_layout(pdf_path))
            if plan:
                E.columns.apply_section_columns(tmp_docx, plan["ncols"], tuple(plan["page_pt"]), body_pt=body_pt)
                E.column_split.apply_band_layout(tmp_docx, plan, heads=(frame or {}).get("headings", []))
            elif frame:
                if not layout:
                    E.columns.apply_section_columns(tmp_docx, frame["cols"], (frame["page_w_pt"], frame["page_h_pt"]),
                                                    body_pt=body_pt)
                E.frame_layout.apply_frame_layout(tmp_docx, frame)
        except PipelineError:
            raise
        except RuntimeError as ex:                                      # md_to_docx: "Pandoc tạo DOCX thất bại."
            raise PipelineError("PANDOC_FAILED", f"{ex} (xem logs/pipeline.log)") from ex
        except AssertionError as ex:
            raise PipelineError("DOCX_BUILD_FAILED", f"Pandoc tạo file Word rỗng: {ex}") from ex
        run.end("build")
        run.check()

        # ------------------------------------------------------------ kiểm tra Word, rồi mới công bố file
        run.begin("validate", VALIDATING, 92)
        note = validate_docx(tmp_docx, work_md)                         # DOCX_INVALID nếu hỏng
        os.replace(tmp_docx, final_docx)
        repo.update(doc_id, docx_size=final_docx.stat().st_size)
        run.end("validate", note)
        run.check()

        # ------------------------------------------------------------ 3-4. dữ liệu RAG (không được làm hỏng kết quả Word)
        rag_ok, rag_note = None, None
        if s.rag_artifacts:
            repo.update(doc_id, progress=97)
            try:
                self._rag_artifacts(E, doc, run_dir, pdf_path, md_path, content_list_path, markdown_text, plan)
                rag_ok = True
            except Cancelled:
                raise
            except Exception as ex:                                     # noqa: BLE001
                import traceback
                log_line("[RAG] " + traceback.format_exc())
                rag_ok, rag_note = False, f"{type(ex).__name__}: {ex}"[:300]

        run.finish(rag_ok=rag_ok, rag_note=rag_note)

    # ------------------------------------------------------------------ RAG
    def _rag_artifacts(self, E, doc: Document, run_dir: Path, pdf_path: Path, md_path: Path,
                       content_list_path: Optional[Path], markdown_text: str, plan) -> None:
        # Làm sạch RIÊNG cho RAG (không đụng markdown_text vì Word còn cần ảnh) — y như main.py bước 3
        rag_md = E.postprocess.clean_markdown(markdown_text, pdf_path=pdf_path, profile=self.s.profile,
                                              sidecar_path=run_dir / "profile.json")
        raw = E.structured.load_raw(content_list_path, md_path, md_text=rag_md)
        if plan:
            raw = E.column_split.remap_content_list(raw, plan)
        blocks = E.structured.normalize_blocks(raw, source=doc.filename, doc_id=doc.id)
        E.structured.save_structured(blocks, run_dir / "structured_data.json")
        chunks = E.chunking.build_chunks(blocks, E.cfg.MAX_CHARS, E.cfg.OVERLAP)
        (run_dir / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        report = E.validate.validate_chunks(chunks, doc.filename, doc.id)
        (run_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log_line(f"[RAG] blocks={len(blocks)} chunks={len(chunks)} validation_ok={report['ok']}")
        if self.s.rag_index:
            from .rag_service import RagService
            RagService(self.s, self.storage, self.engine).build_index(doc.id, chunks)

    # ------------------------------------------------------------------ tiện ích
    @staticmethod
    def _safe(name: str, fn: Callable):
        """Các bước chỉ để cải thiện bố cục (dò cột/khung): lỗi thì bỏ qua, vẫn dựng Word 1 cột."""
        try:
            return fn()
        except Exception as ex:                                         # noqa: BLE001
            log_line(f"[CẢNH BÁO] {name} lỗi ({type(ex).__name__}: {ex}) -> bỏ qua bước này")
            return None

    def _get_spp(self) -> float:
        try:
            return float(self.repo.meta_get("sec_per_page") or self.s.sec_per_page)
        except ValueError:
            return self.s.sec_per_page

    def _record_spp(self, observed: float) -> None:
        """Trung bình trượt số giây/trang để thanh tiến độ lần sau sát thực tế hơn."""
        with self._spp_lock:
            old = self._get_spp()
            self.repo.meta_set("sec_per_page", f"{0.7 * old + 0.3 * observed:.3f}")


class _Run:
    """Theo dõi các bước (stages) của 1 lần chạy và ghi vào DB để giao diện vẽ timeline."""

    def __init__(self, pipeline: Pipeline, doc_id: str, cancel: threading.Event):
        self.p, self.doc_id, self.cancel = pipeline, doc_id, cancel
        self.stages: List[Dict] = []
        self.current: Optional[str] = None

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def begin(self, stage: str, status: str, progress: float) -> None:
        self.check()
        self.current = stage
        self.stages.append({"stage": stage, "status": "running", "started_at": time.time(),
                            "duration_s": None, "note": None})
        self.p.repo.update(self.doc_id, status=status, progress=progress, stages=self.stages)
        log_line(f"--- bước {stage} ---")

    def end(self, stage: str, note: Optional[dict] = None) -> None:
        rec = next(r for r in reversed(self.stages) if r["stage"] == stage)
        rec.update(status="done", duration_s=round(time.time() - rec["started_at"], 2), note=note)
        self.p.repo.update(self.doc_id, stages=self.stages)

    def finish(self, rag_ok, rag_note) -> None:
        self.p.repo.update(self.doc_id, status=DONE, progress=100, finished_at=time.time(), stages=self.stages,
                           error_code=None, error_message=None, rag_ok=rag_ok, rag_note=rag_note)

    def abort(self, status: str, code: Optional[str] = None, message: Optional[str] = None) -> None:
        if self.stages and self.stages[-1]["status"] == "running":
            rec = self.stages[-1]
            rec["duration_s"] = round(time.time() - rec["started_at"], 2)
            if status == FAILED:
                rec["status"], rec["note"] = "failed", {"message": message}
            else:
                rec["status"] = "planned"                                # bị hủy giữa chừng: hiển thị trung tính
        self.p.repo.update(self.doc_id, status=status, finished_at=time.time(), stages=self.stages,
                           error_code=code, error_message=message)
        try:                                                             # dọn file Word dựng dở
            self.p.storage.docx_building_path(self.doc_id).unlink(missing_ok=True)
        except OSError:
            pass
