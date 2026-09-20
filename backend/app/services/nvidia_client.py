"""NVIDIA Nemotron client used only from the backend."""

from threading import Lock
from typing import Any, Iterator

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from ..config import settings


class NVIDIAClientError(RuntimeError):
    """Safe, user-facing NVIDIA API error."""


def is_configured() -> bool:
    return bool(settings.NVIDIA_API_KEY.strip())


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
    enable_thinking: bool = True,
) -> Any:
    """Make one bounded, non-streaming NVIDIA chat request."""
    try:
        return _client().chat.completions.create(
            model=settings.NVIDIA_MODEL,
            messages=messages,
            temperature=settings.NVIDIA_TEMPERATURE,
            top_p=settings.NVIDIA_TOP_P,
            max_tokens=settings.NVIDIA_MAX_TOKENS,
            extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
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
    """Yield answer text as soon as NVIDIA emits streamed deltas."""
    try:
        stream = _client().chat.completions.create(
            model=settings.NVIDIA_MODEL,
            messages=messages,
            temperature=settings.NVIDIA_TEMPERATURE,
            top_p=settings.NVIDIA_TOP_P,
            max_tokens=settings.NVIDIA_MAX_TOKENS,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
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
