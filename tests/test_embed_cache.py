"""Embedding không được chặn việc mở tài liệu: chạy nền, theo lô, cache ra đĩa."""
import threading

import pytest
import requests

import DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026.llm.matchpdf as mp

PAGES = [f"Nội dung trang {i} nói về chủ đề số {i} " * 4 for i in range(1, 71)]  # ~70 chunk


@pytest.fixture()
def calls(monkeypatch):
    log: list[int] = []

    def fake_embed(texts):
        log.append(len(texts))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(mp, "_embed", fake_embed)
    return log


def index(store, pages=PAGES):
    store._index("abc1234567", "x.pdf", store.data_dir / "x.pdf", pages, False, "pypdf")
    store.wait_embeddings("abc1234567", timeout=10)
    return store.docs["abc1234567"]


def test_index_returns_before_embedding_and_uses_batches(tmp_path, monkeypatch):
    gate, batches = threading.Event(), []

    def slow_embed(texts):
        batches.append(len(texts))
        gate.wait(5)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(mp, "_embed", slow_embed)
    store = mp.MatchPdfStore(tmp_path)
    store._index("abc1234567", "x.pdf", tmp_path / "x.pdf", PAGES, False, "pypdf")   # phải trả về dù embed đang treo
    assert store.info("abc1234567")["embed"] == "building"
    assert store.docs["abc1234567"]["embeddings"] is None
    hits, _ = store.retrieve("abc1234567", "chủ đề số 5", [], 3)                    # chat vẫn chạy bằng TF-IDF
    assert hits
    gate.set()
    store.wait_embeddings("abc1234567", timeout=10)
    doc = store.docs["abc1234567"]
    assert doc["embed"] == "ready" and len(doc["embeddings"]) == len(doc["chunks"])
    assert max(batches) <= mp.EMBED_BATCH and len(batches) >= 3


def test_cache_reused_after_restart(tmp_path, calls):
    index(mp.MatchPdfStore(tmp_path))
    first_calls = len(calls)
    assert first_calls >= 3
    doc = index(mp.MatchPdfStore(tmp_path))          # store mới = như sau khi restart BE
    assert len(calls) == first_calls                 # không gọi Ollama lại
    assert doc["embed"] == "ready" and len(doc["embeddings"]) == len(doc["chunks"])


def test_cache_invalidated_when_text_changes(tmp_path, calls):
    index(mp.MatchPdfStore(tmp_path))
    before = len(calls)
    index(mp.MatchPdfStore(tmp_path), PAGES[:-1] + ["Trang cuối đã đổi hoàn toàn nội dung " * 4])
    assert len(calls) > before


def test_embed_failure_falls_back_to_tfidf(tmp_path, monkeypatch):
    def boom(texts):
        raise requests.ConnectionError("ollama off")

    monkeypatch.setattr(mp, "_embed", boom)
    store = mp.MatchPdfStore(tmp_path)
    doc = index(store)
    assert doc["embed"] == "failed" and doc["embeddings"] is None
    assert store.retrieve("abc1234567", "trang 3", [], 3)[0]
