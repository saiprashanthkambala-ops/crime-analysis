"""NVIDIA Nemotron client used only from the backend."""

from threading import Lock
from typing import Any, Iterator

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from ..config import settings


class NVIDIAClientError(RuntimeError):
    """Safe, user-facing NVIDIA API error."""


def is_configured() -> bool:
    return bool(settings.NVIDIA_API_KEY.strip())


# Small per-process cache for repeated exact streamed answers. The analysis
# router builds the key from selected-case data, question, and recent history.
_stream_cache: dict[str, tuple[float, str]] = {}
_stream_cache_lock = Lock()
_STREAM_CACHE_TTL_SECONDS = 300
_STREAM_CACHE_MAX_ITEMS = 128


def get_cached_stream(cache_key: str) -> str | None:
    import time
    now = time.monotonic()
    with _stream_cache_lock:
        item = _stream_cache.get(cache_key)
        if not item:
            return None
        created, value = item
        if now - created > _STREAM_CACHE_TTL_SECONDS:
            _stream_cache.pop(cache_key, None)
            return None
        return value


def set_cached_stream(cache_key: str, value: str) -> None:
    import time
    if not value:
        return
    with _stream_cache_lock:
        _stream_cache[cache_key] = (time.monotonic(), value)
        if len(_stream_cache) > _STREAM_CACHE_MAX_ITEMS:
            oldest_key = min(_stream_cache, key=lambda key: _stream_cache[key][0])
            _stream_cache.pop(oldest_key, None)


_client_instance: OpenAI | None = None
_client_lock = Lock()


def _client() -> OpenAI:
    """Return one reusable client so HTTP keep-alive connections can be pooled."""
    global _client_instance
    if not is_configured():
        raise NVIDIAClientError("NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = OpenAI(
                    base_url=settings.NVIDIA_BASE_URL,
                    api_key=settings.NVIDIA_API_KEY,
                    timeout=settings.NVIDIA_TIMEOUT_SECONDS,
                    max_retries=0,
                )
    return _client_instance


def _provider_error(prefix: str, exc: APIStatusError) -> NVIDIAClientError:
    status = getattr(exc, "status_code", None)
    suffix = f" (HTTP {status})" if status else ""
    return NVIDIAClientError(f"{prefix}{suffix}. Check the NVIDIA API key, model name, quota, or endpoint.")


def chat(
    messages: list[dict[str, str]],
    stream: bool = False,
    enable_thinking: bool | None = None,
) -> Any:
    """Make one bounded NVIDIA chat request using the configured reasoning mode."""
    thinking = settings.NVIDIA_ENABLE_THINKING if enable_thinking is None else enable_thinking
    extra_body: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if thinking and settings.NVIDIA_REASONING_BUDGET > 0:
        extra_body["reasoning_budget"] = settings.NVIDIA_REASONING_BUDGET

    try:
        return _client().chat.completions.create(
            model=settings.NVIDIA_MODEL,
            messages=messages,
            temperature=settings.NVIDIA_TEMPERATURE,
            top_p=settings.NVIDIA_TOP_P,
            max_tokens=settings.NVIDIA_MAX_TOKENS,
            extra_body=extra_body,
            stream=stream,
        )
    except APITimeoutError as exc:
        raise NVIDIAClientError(
            "NVIDIA request timed out. The provider did not return within the configured timeout."
        ) from exc
    except APIConnectionError as exc:
        raise NVIDIAClientError(
            "Could not connect to NVIDIA. Check internet access and NVIDIA_BASE_URL."
        ) from exc
    except APIStatusError as exc:
        raise _provider_error("NVIDIA rejected the request", exc) from exc


def stream_chat(messages: list[dict[str, str]]) -> Iterator[str]:
    """Yield answer text immediately with reasoning disabled for interactive speed."""
    extra_body: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        stream = _client().chat.completions.create(
            model=settings.NVIDIA_MODEL,
            messages=messages,
            temperature=settings.NVIDIA_TEMPERATURE,
            top_p=settings.NVIDIA_TOP_P,
            max_tokens=settings.NVIDIA_MAX_TOKENS,
            extra_body=extra_body,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text
    except APITimeoutError as exc:
        raise NVIDIAClientError(
            "NVIDIA streaming request timed out. The provider did not return within the configured timeout."
        ) from exc
    except APIConnectionError as exc:
        raise NVIDIAClientError(
            "Could not connect to NVIDIA while streaming. Check internet access and NVIDIA_BASE_URL."
        ) from exc
    except APIStatusError as exc:
        raise _provider_error("NVIDIA rejected the streaming request", exc) from exc
