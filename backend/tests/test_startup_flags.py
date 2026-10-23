"""Regression: light FastAPI startup must not auto-load AI models on small instances."""
import threading

from backend.app.core.config import Settings


def test_model_prewarm_defaults_off(monkeypatch):
    monkeypatch.delenv("EMBED_PREWARM", raising=False)
    monkeypatch.delenv("MINERU_PREWARM", raising=False)
    settings = Settings(_env_file=None)
    assert settings.embed_prewarm is False
    assert settings.mineru_prewarm is False


def test_model_prewarm_can_be_enabled(monkeypatch):
    monkeypatch.setenv("EMBED_PREWARM", "true")
    monkeypatch.setenv("MINERU_PREWARM", "1")
    settings = Settings(_env_file=None)
    assert settings.embed_prewarm is True
    assert settings.mineru_prewarm is True


def test_default_lifespan_skips_ai_prewarm_threads(client):
    assert client.get("/api/health").status_code == 200
    running = {thread.name for thread in threading.enumerate()}
    assert "warm-embed" not in running
    assert "warm-mineru" not in running
