import pytest
from app.services.ai_telemetry import (
    record_ai_metric,
    get_ai_telemetry_summary,
    reset_ai_telemetry,
)


@pytest.fixture(autouse=True)
def clean_telemetry():
    reset_ai_telemetry()
    yield
    reset_ai_telemetry()


def test_record_and_summary_percentiles():
    # Record 10 metrics with known TTFT and durations
    for i in range(1, 11):
        record_ai_metric(
            endpoint="generate_analysis",
            model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            used_fallback=False,
            ttft_ms=i * 100.0,
            duration_ms=i * 1000.0,
            token_count=i * 20,
            retries=0,
            success=True,
        )

    summary = get_ai_telemetry_summary()
    assert summary["total_requests"] == 10
    assert summary["successful_requests"] == 10
    assert summary["failed_requests"] == 0
    assert summary["fallback_count"] == 0
    assert summary["fallback_rate_pct"] == 0.0

    # Percentiles
    assert summary["ttft"]["min_ms"] == 100.0
    assert summary["ttft"]["max_ms"] == 1000.0
    assert summary["ttft"]["p50_ms"] is not None
    assert summary["ttft"]["p95_ms"] is not None
    assert summary["duration"]["p50_ms"] is not None
    assert summary["duration"]["p95_ms"] is not None

    # Check model usage counter
    assert summary["models_used"]["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"] == 10


def test_fallback_rate_and_retries():
    # 3 primary, 1 fallback
    record_ai_metric("analysis_chat", "model-primary", False, 200.0, 1000.0, 50, 0, True)
    record_ai_metric("analysis_chat", "model-primary", False, 220.0, 1100.0, 50, 0, True)
    record_ai_metric("analysis_chat", "model-primary", False, 210.0, 1050.0, 50, 0, True)
    record_ai_metric("analysis_chat", "model-fallback", True, 450.0, 2500.0, 80, 1, True)

    summary = get_ai_telemetry_summary()
    assert summary["total_requests"] == 4
    assert summary["fallback_count"] == 1
    assert summary["fallback_rate_pct"] == 25.0
    assert summary["models_used"]["model-primary"] == 3
    assert summary["models_used"]["model-fallback"] == 1


def test_sanitization_no_sensitive_data():
    record_ai_metric(
        endpoint="generate_analysis",
        model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        used_fallback=False,
        ttft_ms=150.0,
        duration_ms=1200.0,
        token_count=100,
        retries=0,
        success=True,
    )

    summary = get_ai_telemetry_summary()
    recent = summary["recent_metrics"]
    assert len(recent) == 1
    m = recent[0]

    # Verify no prompt, key, secret, or context content exists in telemetry
    assert "prompt" not in m
    assert "api_key" not in m
    assert "secret" not in m
    assert "context" not in m
    assert "case_data" not in m
    assert m["endpoint"] == "generate_analysis"
    assert m["success"] is True


def test_admin_telemetry_rbac(client, admin_headers, auth_headers):
    # Admin access -> 200 OK
    res_admin = client.get("/api/admin/telemetry/ai", headers=admin_headers)
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "total_requests" in data
    assert "ttft" in data
    assert "duration" in data

    # Investigator access -> 403 Forbidden
    res_investigator = client.get("/api/admin/telemetry/ai", headers=auth_headers)
    assert res_investigator.status_code == 403

    # Unauthenticated access -> 401 Unauthorized
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as unauth_client:
        res_unauth = unauth_client.get("/api/admin/telemetry/ai")
        assert res_unauth.status_code == 401
