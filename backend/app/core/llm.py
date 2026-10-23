"""Mô hình ngôn ngữ dùng cho chat: none | qwen_local | ollama (nạp 1 lần, dùng lại)."""
import json
import threading
from abc import ABC, abstractmethod
from typing import Iterator, Optional

import httpx

from backend.app.core.config import get_settings


class LLMError(Exception):
    """Lỗi khi nạp hoặc gọi mô hình ngôn ngữ."""


class LLMBackend(ABC):
    name: str = "llm"

    @abstractmethod
    def stream(self, system: str, user: str) -> Iterator[str]:
        """Sinh câu trả lời, trả về từng đoạn text."""


class QwenLocal(LLMBackend):
    def __init__(self, model_name: str, max_new_tokens: int = 768):
        from llm.src.ask_rag import load_llm     # tái dùng loader của pipeline gốc
        self.name = f"Qwen local ({model_name})"
        self.tok, self.model = load_llm(model_name)
        self.max_new_tokens = max_new_tokens
        self._gen_lock = threading.Lock()     # mỗi lần chỉ 1 lượt sinh

    def stream(self, system: str, user: str) -> Iterator[str]:
        from transformers import TextIteratorStreamer

        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        text = self.tok.apply_chat_template(messages, tokenize=False,
                                            add_generation_prompt=True)
        inputs = self.tok([text], return_tensors="pt").to(self.model.device)
        streamer = TextIteratorStreamer(self.tok, skip_prompt=True, skip_special_tokens=True)
        errors: list = []

        def _run():
            try:
                self.model.generate(**inputs, streamer=streamer,
                                    max_new_tokens=self.max_new_tokens,
                                    do_sample=True, temperature=0.2, top_p=0.9)
            except Exception as e:                # noqa: BLE001
                errors.append(e)
                streamer.end()

        with self._gen_lock:
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            for piece in streamer:
                if piece:
                    yield piece
            t.join()
        if errors:
            raise LLMError(f"Qwen sinh câu trả lời thất bại: {errors[0]}")


class OllamaClient(LLMBackend):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"Ollama ({model})"

    def stream(self, system: str, user: str) -> Iterator[str]:
        payload = {"model": self.model, "stream": True,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "options": {"temperature": 0.2}}
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload,
                              timeout=httpx.Timeout(300.0, connect=5.0)) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise LLMError(f"Ollama trả về {resp.status_code}: {resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
        except httpx.HTTPError as e:
            raise LLMError(f"Không kết nối được Ollama tại {self.base_url}: {e}") from e


_llm: Optional[LLMBackend] = None
_loaded = False
_lock = threading.Lock()


def get_llm() -> Optional[LLMBackend]:
    """Trả về LLM đã nạp (singleton). None nghĩa là LLM_BACKEND=none."""
    global _llm, _loaded
    with _lock:
        if _loaded:
            return _llm
        s = get_settings()
        try:
            if s.llm_backend == "qwen_local":
                from DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026.llm.src.config import LLM_NAME
                _llm = QwenLocal(s.llm_name or LLM_NAME)
            elif s.llm_backend == "ollama":
                _llm = OllamaClient(s.ollama_url, s.ollama_model)
            else:
                _llm = None
        except Exception as e:                    # noqa: BLE001
            raise LLMError(f"Không nạp được mô hình '{s.llm_backend}': {e}") from e
        _loaded = True
        return _llm