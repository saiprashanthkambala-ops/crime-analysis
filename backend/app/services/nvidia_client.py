"""NVIDIA Nemotron client used only from the backend."""

from typing import Any

from openai import OpenAI

from ..config import settings


def is_configured() -> bool:
    return bool(settings.NVIDIA_API_KEY.strip())


def _client() -> OpenAI:
    if not is_configured():
        raise RuntimeError("NVIDIA API is not configured. Set NVIDIA_API_KEY.")
    return OpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=settings.NVIDIA_API_KEY,
    )


def chat(messages: list[dict[str, str]], *, stream: bool = False) -> Any:
    """Call the NVIDIA OpenAI-compatible chat endpoint."""
    return _client().chat.completions.create(
        model=settings.NVIDIA_MODEL,
        messages=messages,
        temperature=settings.NVIDIA_TEMPERATURE,
        top_p=settings.NVIDIA_TOP_P,
        max_tokens=settings.NVIDIA_MAX_TOKENS,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": settings.NVIDIA_ENABLE_THINKING},
            "reasoning_budget": settings.NVIDIA_REASONING_BUDGET,
        },
        stream=stream,
    )
