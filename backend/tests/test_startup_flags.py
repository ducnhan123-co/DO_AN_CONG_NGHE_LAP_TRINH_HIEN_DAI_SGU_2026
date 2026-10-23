"""Model-free startup regression tests."""
import threading
from backend.app.core.config import Settings


def test_safe_defaults(monkeypatch):
    monkeypatch.delenv("AI_PIPELINE_ENABLED", raising=False)
    monkeypatch.delenv("MINERU_PREWARM", raising=False)
    settings = Settings(_env_file=None)
    assert settings.ai_pipeline_enabled is False
    assert settings.mineru_prewarm is False
    assert not hasattr(settings, "embed_prewarm")
    assert not hasattr(settings, "llm_backend")


def test_mac_mode(monkeypatch):
    monkeypatch.setenv("AI_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("MINERU_PREWARM", "0")
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    settings = Settings(_env_file=None)
    assert settings.ai_pipeline_enabled is True
    assert settings.mineru_prewarm is False
    assert settings.serve_frontend is True


def test_no_e5_on_lifespan(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").json()["search_backend"] == "keyword_bm25"
    assert "warm-embed" not in {t.name for t in threading.enumerate()}
