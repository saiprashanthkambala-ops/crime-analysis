"""Lightweight, in-memory AI performance and latency telemetry.

Tracks key operational metrics (TTFT, total generation time, token counts,
model fallback rate, and provider capacity retry frequency) to enable
investigators' administrators to monitor AI reliability and cluster latency.

SECURITY GUARANTEES:
- Strictly NO prompt contents or model responses are stored.
- Strictly NO API keys, JWT secrets, passwords, or credentials are stored.
- Strictly NO case-specific investigation records are exposed.
- Accessible only to users with the 'admin' role via RBAC.
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

_MAX_TELEMETRY_ENTRIES = 200
_telemetry_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_TELEMETRY_ENTRIES)
_telemetry_lock = Lock()


def record_ai_metric(
    endpoint: str,
    model: str,
    ttft_ms: float | None = None,
    total_duration_ms: float | None = None,
    duration_ms: float | None = None,
    token_count: int = 0,
    used_fallback: bool = False,
    retry_count: int = 0,
    retries: int = 0,
    status: str = "completed",
    success: bool | None = None,
    case_count: int = 1,
    error_type: str | None = None,
) -> None:
    """Record a bounded, sanitized telemetry event for AI streaming/chat."""
    now_utc = datetime.now(timezone.utc).isoformat()
    actual_duration = duration_ms if duration_ms is not None else total_duration_ms
    actual_retries = retries if retries != 0 else retry_count
    if success is not None:
        actual_status = "completed" if success else "failed"
    else:
        actual_status = status

    record = {
        "timestamp": now_utc,
        "endpoint": str(endpoint),
        "model": str(model),
        "ttft_ms": round(float(ttft_ms), 1) if ttft_ms is not None else None,
        "duration_ms": round(float(actual_duration), 1) if actual_duration is not None else None,
        "total_duration_ms": round(float(actual_duration), 1) if actual_duration is not None else None,
        "token_count": int(token_count),
        "used_fallback": bool(used_fallback),
        "retry_count": int(actual_retries),
        "status": str(actual_status),
        "success": (actual_status == "completed"),
        "case_count": int(case_count),
        "error_type": str(error_type) if error_type else None,
    }

    with _telemetry_lock:
        _telemetry_buffer.append(record)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * pct
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    d = k - f
    return round(values_sorted[f] + (values_sorted[c] - values_sorted[f]) * d, 1)


def get_ai_telemetry_summary() -> dict[str, Any]:
    """Calculate aggregated p50/p95 latency, fallback rate, and recent events."""
    with _telemetry_lock:
        events = list(_telemetry_buffer)

    total_requests = len(events)
    if total_requests == 0:
        return {
            "total_requests": 0,
            "completed_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "fallback_count": 0,
            "fallback_rate": 0.0,
            "fallback_rate_pct": 0.0,
            "retry_events_count": 0,
            "ttft": {
                "p50_ms": None,
                "p95_ms": None,
                "avg_ms": None,
                "min_ms": None,
                "max_ms": None,
            },
            "duration": {
                "p50_ms": None,
                "p95_ms": None,
                "avg_ms": None,
                "min_ms": None,
                "max_ms": None,
            },
            "model_breakdown": {},
            "models_used": {},
            "recent_events": [],
            "recent_metrics": [],
        }

    completed = [e for e in events if e.get("status") == "completed"]
    failed = [e for e in events if e.get("status") != "completed"]
    fallbacks = [e for e in events if e.get("used_fallback")]
    retries = [e for e in events if (e.get("retry_count") or 0) > 0]

    ttft_values = [e["ttft_ms"] for e in completed if e.get("ttft_ms") is not None]
    duration_values = [e["total_duration_ms"] for e in completed if e.get("total_duration_ms") is not None]

    model_counts: dict[str, int] = {}
    for e in events:
        m = e.get("model") or "unknown"
        model_counts[m] = model_counts.get(m, 0) + 1

    return {
        "total_requests": total_requests,
        "completed_requests": len(completed),
        "successful_requests": len(completed),
        "failed_requests": len(failed),
        "fallback_count": len(fallbacks),
        "fallback_rate": round(len(fallbacks) / total_requests, 3),
        "fallback_rate_pct": round((len(fallbacks) / total_requests) * 100, 1),
        "retry_events_count": len(retries),
        "ttft": {
            "p50_ms": _percentile(ttft_values, 0.50),
            "p95_ms": _percentile(ttft_values, 0.95),
            "avg_ms": round(statistics.mean(ttft_values), 1) if ttft_values else None,
            "min_ms": min(ttft_values) if ttft_values else None,
            "max_ms": max(ttft_values) if ttft_values else None,
        },
        "duration": {
            "p50_ms": _percentile(duration_values, 0.50),
            "p95_ms": _percentile(duration_values, 0.95),
            "avg_ms": round(statistics.mean(duration_values), 1) if duration_values else None,
            "min_ms": min(duration_values) if duration_values else None,
            "max_ms": max(duration_values) if duration_values else None,
        },
        "model_breakdown": model_counts,
        "models_used": model_counts,
        "recent_events": events[-20:],
        "recent_metrics": events[-20:],
    }


def clear_ai_telemetry() -> None:
    """Clear in-memory buffer (primarily used in test suites)."""
    with _telemetry_lock:
        _telemetry_buffer.clear()


reset_ai_telemetry = clear_ai_telemetry
