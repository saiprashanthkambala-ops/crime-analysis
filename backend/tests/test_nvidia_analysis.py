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
    assert fresh.NVIDIA_MODEL in (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
    )
    assert fresh.NVIDIA_FALLBACK_MODEL in (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
    )


def test_nvidia_client_is_disabled_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
    assert nvidia_client.is_configured() is False


def test_nvidia_client_uses_configured_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    monkeypatch.setattr(settings, "NVIDIA_ENABLE_THINKING", True)

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


class _Chunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})]


def test_nvidia_stream_normal(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    monkeypatch.setattr(settings, "NVIDIA_FALLBACK_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            calls.append(kwargs["model"])
            return iter([_Chunk("Hello "), _Chunk("world")])

    monkeypatch.setattr(nvidia_client, "_client_instance", FakeClient())

    tokens = list(nvidia_client.stream_chat([{"role": "user", "content": "hi"}]))
    assert tokens == ["Hello ", "world"]
    assert calls == ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"]


def test_nvidia_stream_temporary_capacity_retry_success(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    monkeypatch.setattr(settings, "NVIDIA_FALLBACK_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    sleeps = []
    monkeypatch.setattr(nvidia_client.time, "sleep", lambda s: sleeps.append(s))

    attempt_count = 0

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                # Simulate NVIDIA hosted cluster limit
                raise RuntimeError("Worker local total request limit reached (16/16)")
            return iter([_Chunk("Recovered "), _Chunk("after retry")])

    monkeypatch.setattr(nvidia_client, "_client_instance", FakeClient())

    tokens = list(nvidia_client.stream_chat([{"role": "user", "content": "hi"}]))
    assert tokens == ["Recovered ", "after retry"]
    assert attempt_count == 2
    assert sleeps == [0.5]  # First backoff delay


def test_nvidia_stream_repeated_capacity_failure_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    monkeypatch.setattr(settings, "NVIDIA_FALLBACK_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    sleeps = []
    monkeypatch.setattr(nvidia_client.time, "sleep", lambda s: sleeps.append(s))

    models_called = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            model = kwargs["model"]
            models_called.append(model)
            if model == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning":
                # Fails all attempts on primary
                raise RuntimeError("Worker local total request limit reached (16/16)")
            return iter([_Chunk("From fallback model")])

    monkeypatch.setattr(nvidia_client, "_client_instance", FakeClient())

    tokens = list(nvidia_client.stream_chat([{"role": "user", "content": "hi"}]))
    assert tokens == ["From fallback model"]
    # Primary attempted 1 initial + 2 retries = 3 times, then fallback 1 time
    assert models_called.count("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning") == 3
    assert models_called.count("nvidia/nemotron-3.5-lightning-30b-a3b") == 1
    assert sleeps == [0.5, 1.0]


def test_nvidia_stream_non_capacity_error_falls_back_without_retry(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    monkeypatch.setattr(settings, "NVIDIA_FALLBACK_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    sleeps = []
    monkeypatch.setattr(nvidia_client.time, "sleep", lambda s: sleeps.append(s))

    models_called = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            model = kwargs["model"]
            models_called.append(model)
            if model == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning":
                raise ValueError("Permanent malformed prompt")
            return iter([_Chunk("Fallback answer")])

    monkeypatch.setattr(nvidia_client, "_client_instance", FakeClient())

    tokens = list(nvidia_client.stream_chat([{"role": "user", "content": "hi"}]))
    assert tokens == ["Fallback answer"]
    # Non-capacity error does not backoff retry
    assert models_called.count("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning") == 1
    assert models_called.count("nvidia/nemotron-3.5-lightning-30b-a3b") == 1
    assert sleeps == []


def test_nvidia_stream_mid_stream_stall_raises_client_error(monkeypatch):
    import pytest
    from openai import APITimeoutError

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")

    class StallingStream:
        def __iter__(self):
            yield _Chunk("Beginning of response")
            raise APITimeoutError("Read timeout while waiting for next token")

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            return StallingStream()

    monkeypatch.setattr(nvidia_client, "_client_instance", FakeClient())

    with pytest.raises(nvidia_client.NVIDIAClientError) as exc_info:
        list(nvidia_client.stream_chat([{"role": "user", "content": "hi"}]))

    assert "stalled" in str(exc_info.value).lower()
