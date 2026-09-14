"""NVIDIA Nemotron client used only from the backend."""

from typing import Any
from openai import APIConnectionError, APITimeoutError, OpenAI
from ..config import settings

class NVIDIAClientError(RuntimeError):
    """Safe, user-facing NVIDIA API error."""

def is_configured() -> bool:
    return bool(settings.NVIDIA_API_KEY.strip())

def _client() -> OpenAI:
    if not is_configured():
        raise NVIDIAClientError("NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")
    return OpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=settings.NVIDIA_API_KEY,
        timeout=settings.NVIDIA_TIMEOUT_SECONDS,
        max_retries=0,
    )

def chat(messages: list[dict[str, str]]) -> Any:
    """Make one bounded, non-streaming NVIDIA chat request."""
    extra_body = {}
    if settings.NVIDIA_ENABLE_THINKING:
        extra_body = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": settings.NVIDIA_REASONING_BUDGET,
        }
    try:
        kwargs = {
            "model": settings.NVIDIA_MODEL,
            "messages": messages,
            "temperature": settings.NVIDIA_TEMPERATURE,
            "top_p": settings.NVIDIA_TOP_P,
            "max_tokens": settings.NVIDIA_MAX_TOKENS,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        return _client().chat.completions.create(**kwargs)
    except APITimeoutError as exc:
        raise NVIDIAClientError(
            "NVIDIA request timed out. Check NVIDIA_API_KEY, network access, and the NVIDIA endpoint."
        ) from exc
    except APIConnectionError as exc:
        raise NVIDIAClientError(
            "Could not connect to NVIDIA. Check internet access and NVIDIA_BASE_URL."
        ) from exc
