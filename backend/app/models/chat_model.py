"""Nghiệp vụ chat: truy xuất RAG (LlamaIndex, có trang thật), gọi LLM, phát 'suy nghĩ', lưu hội thoại."""
import logging
from typing import Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.llm import LLMError, get_llm
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
    "Trả lời bằng ngôn ngữ của câu hỏi."
)
NO_RESULT = "Không tìm thấy thông tin liên quan trong tài liệu."
_ERROR_STATUS = {"LLM_UNAVAILABLE": 503}

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
             f"{h['text'][:600].strip()}" for h in hits[:3]]
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


def stream_events(document_id: str, question: str, top_k: Optional[int] = None) -> Iterator[Event]:
    """Sinh chuỗi sự kiện: thinking* -> token* -> citations -> done (hoặc error)."""
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

        citations = [{"index": i, "page": h.get("page"), "section": h.get("section") or "",
                      "score": round(h.get("score") or 0.0, 4), "snippet": _snippet(h["text"])}
                     for i, h in enumerate(hits, 1)]

        if not hits:
            yield think("retrieved", "Không tìm thấy đoạn nào liên quan.")
            answer_text = NO_RESULT
            yield "token", {"text": answer_text}
        else:
            pages = sorted({h["page"] for h in hits if h.get("page") is not None})
            yield think("retrieved", f"Tìm thấy {len(hits)} đoạn liên quan"
                        + (f", trang {', '.join(map(str, pages))}" if pages else "."))
            model = get_llm()
            if model is None:
                yield think("generate", "Chưa bật mô hình ngôn ngữ, trích trực tiếp đoạn liên quan nhất.")
                answer_text = _extractive_answer(hits)
                yield "token", {"text": answer_text}
            else:
                yield think("generate", f"Đang soạn câu trả lời bằng {model.name}...")
                parts: List[str] = []
                for piece in model.stream(SYSTEM_PROMPT, _build_prompt(question, hits, history)):
                    parts.append(piece)
                    yield "token", {"text": piece}
                answer_text = "".join(parts).strip() or NO_RESULT

        yield "citations", {"items": citations}
        message_id = _save_messages(document_id, question, answer_text, thinking, citations)
        yield "done", ChatResponse(message_id=message_id, document_id=document_id,
                                   answer=answer_text, citations=citations,
                                   thinking=thinking).model_dump()
    except LLMError as e:
        logger.warning("LLM lỗi: %s", e)
        yield "error", {"code": "LLM_UNAVAILABLE", "message": str(e)}
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