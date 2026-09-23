"""Controller: chat với tài liệu, hỗ trợ JSON và SSE (kèm 'suy nghĩ')."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

from backend.app.models import chat_model
from backend.app.models.database import get_db
from backend.app.views.schemas import ChatRequest, ChatResponse, errors

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

_SSE_DOC = {"description": "Khi stream=true (hoặc Accept: text/event-stream): "
                           "các sự kiện thinking, token, citations, done, error.",
            "content": {"text/event-stream": {}}}
def _sse_event(event: str, data: dict) -> dict:
    """Định dạng 1 sự kiện SSE cho sse-starlette."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@router.post("/documents/{document_id}/chat", tags=["chat"], response_model=ChatResponse,
             summary="Chat với tài liệu (answer + citations, tùy chọn stream)",
             responses={200: _SSE_DOC, **errors(404, 409, 422, 500, 503)})
def chat(document_id: str, body: ChatRequest, request: Request, db: DbSession):
    chat_model.ensure_ready(db, document_id)     # lỗi 404/409 trả về trước khi stream

    wants_stream = body.stream or "text/event-stream" in request.headers.get("accept", "")
    if not wants_stream:
        return chat_model.answer(document_id, body.question, body.top_k)

    events = chat_model.stream_events(document_id, body.question, body.top_k)

    async def event_source():
        async for event, data in iterate_in_threadpool(events):
            yield _sse_event(event, data)

    return EventSourceResponse(event_source())