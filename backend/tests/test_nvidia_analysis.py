"""Offline tests for the NVIDIA analysis integration."""

from app.config import Settings, settings
from app.services import nvidia_client


def test_nvidia_settings_defaults(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    fresh = Settings()
    assert fresh.NVIDIA_API_KEY == ""
    assert fresh.NVIDIA_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert fresh.NVIDIA_MODEL == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_nvidia_client_is_disabled_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
    assert nvidia_client.is_configured() is False


def test_nvidia_client_uses_configured_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr(nvidia_client, "OpenAI", FakeClient)

    result = nvidia_client.chat(
        [{"role": "user", "content": "test"}],
        stream=False,
    )

    assert result == {"ok": True}
    assert captured["client"]["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert captured["client"]["api_key"] == "unit-test-key"
    assert captured["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert captured["stream"] is False
    assert captured["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
