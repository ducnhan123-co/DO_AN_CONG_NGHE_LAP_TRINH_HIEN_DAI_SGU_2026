"""Nghiệp vụ chat: truy xuất RAG (LlamaIndex, có trang thật), gọi LLM, phát 'suy nghĩ', lưu hội thoại."""
import logging
import re
from typing import Iterator, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.models import document_model, pipeline_model
from backend.app.models.database import Document, DocumentStatus, Message, SessionLocal
from backend.app.views.schemas import ChatResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là trợ lý hỏi đáp tài liệu toán học. Chỉ trả lời dựa trên NGỮ CẢNH được cung cấp. "
    "Nếu ngữ cảnh không đủ thông tin, hãy nói rõ tài liệu không đề cập. "
    "Giữ nguyên công thức LaTeX (trong $...$ hoặc $$...$$). "
    "Khi dùng thông tin từ trang nào, ghi chú ngay sau ý đó dạng [số trang], ví dụ [12]. "
    "Nếu câu hỏi tiếp nối lịch sử hội thoại phía trên, hãy trả lời nối tiếp cho phù hợp. "
    "BẮT BUỘC: luôn trả lời bằng tiếng Việt, không dùng tiếng Anh hay ngôn ngữ khác "
    "(trừ thuật ngữ chuyên môn và công thức LaTeX giữ nguyên)."
)
NO_RESULT = "Không tìm thấy thông tin liên quan trong tài liệu."
_ERROR_STATUS = {}

Event = Tuple[str, dict]


def ensure_ready(db: Session, document_id: str) -> Document:
    doc = document_model.get_document(db, document_id)
    if doc.status == DocumentStatus.failed.value:
        raise AppError(409, "DOCUMENT_FAILED", "Tài liệu xử lý thất bại, không thể chat.",
                       {"error": doc.error_code})
    if doc.status != DocumentStatus.ready.value:
        raise AppError(409, "DOCUMENT_NOT_READY",
                       "Tài liệu đang được xử lý. Hãy theo dõi qua GET /jobs/{id}.",
                       {"status": doc.status})
    return doc


def _snippet(text: str, n: int = 300) -> str:
    return " ".join(text.split())[:n]


def _recent_history(document_id: str, turns: int = 3) -> List[dict]:
    """Lấy tối đa `turns` lượt hỏi-đáp gần nhất (cũ -> mới) để giữ ngữ cảnh hội thoại."""
    if turns <= 0:
        return []
    from sqlalchemy import select
    with SessionLocal() as db:
        rows = db.scalars(select(Message).where(Message.document_id == document_id)
                          .order_by(Message.created_at.desc()).limit(turns * 2)).all()
    rows = list(reversed(rows))  # cũ -> mới
    return [{"role": r.role, "content": r.content} for r in rows]


def _search_query(question: str, history: List[dict]) -> str:
    """Gộp câu hỏi user gần nhất vào câu hỏi hiện tại để tìm kiếm không mất ngữ cảnh."""
    prev_questions = [h["content"] for h in history if h["role"] == "user"]
    if not prev_questions:
        return question
    return f"{prev_questions[-1]} {question}"


_PAGE_RE = re.compile(r"(?:trang|page|p\.?)\s*(\d+)(?:\s*[-–—đến]+\s*(\d+))?", re.IGNORECASE)


def _wanted_pages(question: str) -> Set[int]:
    """Trang user hỏi đích danh ('trang 5', 'page 5-7', 'trang 5, 6')."""
    pages: Set[int] = set()
    for m in _PAGE_RE.finditer(question):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        lo, hi = min(a, b), max(a, b)
        if 1 <= lo <= 100000 and hi - lo <= 50:
            pages.update(range(lo, hi + 1))
    return pages


def _hit_pages(hit: dict) -> Set[int]:
    """Mọi trang mà chunk này phủ (chunk có thể spanning nhiều trang)."""
    out: Set[int] = set()
    if isinstance(hit.get("page"), int):
        out.add(hit["page"])
    for key in ("pages",):
        val = hit.get(key)
        if isinstance(val, (list, tuple)):
            out.update(p for p in val if isinstance(p, int))
    for key in ("page_end",):
        val = hit.get(key)
        if isinstance(val, int) and out:
            out.update(range(min(out), val + 1))
    return out


def _filter_pages(hits: List[dict], pages: Set[int]) -> List[dict]:
    return [h for h in hits if _hit_pages(h) & pages]


def _page_blocks(document_id: str, pages: Set[int], max_chars: int = 4000) -> tuple:
    """Lấy thẳng block theo trang từ structured_data.json (không qua semantic).
    Trả về (hits, max_page). Trang hỏi đích danh mà semantic không tìm ra
    (vd. 'trang 5 có công thức gì') thì đường này luôn trúng."""
    from backend.app.core.config import get_settings
    path = get_settings().doc_dir(document_id) / "structured_data.json"
    try:
        import json
        blocks = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0
    max_page = 0
    by_page: dict = {}
    for b in blocks:
        p = b.get("page")
        if isinstance(p, int):
            max_page = max(max_page, p)
            if p in pages:
                by_page.setdefault(p, []).append(b)
    hits = []
    for p in sorted(by_page):
        parts, total = [], 0
        section = ""
        for b in by_page[p]:
            section = section or b.get("section") or ""
            t = (b.get("text") or "").strip()
            if not t or total + len(t) > max_chars:
                continue
            parts.append(t)
            total += len(t)
        if parts:
            hits.append({"text": "\n\n".join(parts), "page": p, "section": section,
                         "score": 1.0, "full": True})
    return hits, max_page


def _build_prompt(question: str, hits: List[dict], history: List[dict]) -> str:
    ctx = "\n\n".join(
        f"[trang {h['page'] if h.get('page') is not None else '?'}] {h.get('section') or ''}\n{h['text']}"
        for h in hits)
    hist_text = ""
    if history:
        lines = [f"{'Người dùng' if h['role']=='user' else 'Trợ lý'}: {h['content']}" for h in history]
        hist_text = "LỊCH SỬ HỘI THOẠI GẦN ĐÂY:\n" + "\n".join(lines) + "\n\n"
    return f"{hist_text}NGỮ CẢNH:\n{ctx}\n\nCÂU HỎI: {question}\n\nTRẢ LỜI:"


def _extractive_answer(hits: List[dict]) -> str:
    parts = [f"[trang {h['page'] if h.get('page') is not None else '?'}] {h.get('section') or ''}\n"
             f"{h['text'].strip() if h.get('full') else h['text'][:600].strip()}" for h in hits[:3]]
    return "Các đoạn liên quan nhất trong tài liệu:\n\n" + "\n\n".join(parts)


def _save_messages(document_id: str, question: str, answer_text: str,
                   thinking: list, citations: list) -> str:
    with SessionLocal() as db:
        db.add(Message(document_id=document_id, role="user", content=question))
        assistant = Message(document_id=document_id, role="assistant", content=answer_text,
                            thinking=thinking, citations=citations)
        db.add(assistant)
        db.commit()
        return assistant.id


def stream_events(document_id: str, question: str, top_k: Optional[int] = None,
                  client_history: Optional[List[dict]] = None,
                  persist: bool = True) -> Iterator[Event]:
    settings = get_settings()
    k = top_k or settings.top_k
    history = _recent_history(document_id, settings.chat_history_turns)
    thinking: list = []

    def think(step: str, text: str) -> Event:
        thinking.append({"step": step, "text": text})
        return "thinking", {"step": step, "text": text}

    try:
        yield think("analyze", "Đang phân tích câu hỏi...")
        yield think("retrieve", f"Đang tìm {k} đoạn liên quan trong tài liệu...")
        search_q = _search_query(question, history)
        hits = pipeline_model.search(document_id, search_q, k)
        wanted = _wanted_pages(question)
        page_reported = False
        if wanted and hits:
            # user hỏi đích danh trang -> chỉ giữ chunk thuộc trang đó;
            # không đủ thì tìm rộng hơn, cuối cùng lấy thẳng block theo trang.
            hits = _filter_pages(hits, wanted)
            if not hits:
                hits = _filter_pages(pipeline_model.search(document_id, search_q, k * 4), wanted)
            if not hits:
                hits, max_page = _page_blocks(document_id, wanted)
                page_reported = True
                if hits:
                    yield think("retrieved",
                                f"Lấy trực tiếp nội dung trang {', '.join(map(str, sorted(wanted)))}.")
                else:
                    yield think("retrieved",
                                f"Trang {', '.join(map(str, sorted(wanted)))} không có nội dung"
                                + (f" (tài liệu có {max_page} trang)." if max_page else "."))
            else:
                yield think("retrieved", f"Đã lọc đúng trang {', '.join(map(str, sorted(wanted)))}.")

        citations = [{"index": i, "page": h.get("page"), "section": h.get("section") or "",
                      "score": round(h.get("score") or 0.0, 4), "snippet": _snippet(h["text"])}
                     for i, h in enumerate(hits, 1)]

        if not hits:
            if not page_reported:
                yield think("retrieved", "Không tìm thấy đoạn nào liên quan.")
            if wanted:
                # đã báo chi tiết ở trên (lấy trực tiếp / trang không tồn tại) -> dùng lại câu đó.
                answer_text = (f"Trang {', '.join(map(str, sorted(wanted)))} không có nội dung khớp câu hỏi. "
                               f"Thử hỏi theo nội dung thay vì số trang.")
            else:
                answer_text = NO_RESULT
            yield "token", {"text": answer_text}
        else:
            pages = sorted({h["page"] for h in hits if h.get("page") is not None})
            yield think("retrieved", f"Tìm thấy {len(hits)} đoạn liên quan"
                        + (f", trang {', '.join(map(str, pages))}" if pages else "."))
            yield think("extract", "Tra cứu theo từ khóa; trích nguyên văn, không sinh câu trả lời AI.")
            answer_text = _extractive_answer(hits)
            yield "token", {"text": answer_text}

        yield "citations", {"items": citations}
        if persist:
            message_id = _save_messages(document_id, question, answer_text, thinking, citations)
        else:
            import uuid
            message_id = uuid.uuid4().hex   # chỉ để điền schema, không ghi DB
        yield "done", ChatResponse(message_id=message_id, document_id=document_id,
                                   answer=answer_text, citations=citations,
                                   thinking=thinking).model_dump()
    except AppError as e:
        yield "error", {"code": e.code, "message": e.message}
    except Exception:                              # noqa: BLE001
        logger.exception("Chat thất bại (doc=%s)", document_id)
        yield "error", {"code": "CHAT_FAILED",
                        "message": "Không thể tạo câu trả lời. Vui lòng thử lại."}


def answer(document_id: str, question: str, top_k: Optional[int] = None) -> ChatResponse:
    """Chế độ JSON (không stream): gom toàn bộ sự kiện thành 1 response."""
    final: Optional[dict] = None
    for event, data in stream_events(document_id, question, top_k):
        if event == "error":
            raise AppError(_ERROR_STATUS.get(data["code"], 500), data["code"], data["message"])
        if event == "done":
            final = data
    if final is None:
        raise AppError(500, "CHAT_FAILED", "Không thể tạo câu trả lời.")
    return ChatResponse(**final)