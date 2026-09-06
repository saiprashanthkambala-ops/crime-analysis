"""Authentication + RBAC tests."""
import pytest


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "investigator1", "password": "wrong"})
    assert r.status_code == 401


def test_missing_token(client):
    assert client.get("/api/cases").status_code == 401


def test_invalid_token(client):
    r = client.get("/api/cases", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_investigator_cannot_access_admin(client, auth_headers):
    assert client.get("/api/admin/users", headers=auth_headers).status_code == 403
    assert client.get("/api/audit", headers=auth_headers).status_code == 403


def test_admin_can_access_admin(client, admin_headers):
    assert client.get("/api/admin/users", headers=admin_headers).status_code == 200
    assert client.get("/api/audit", headers=admin_headers).status_code == 200


def test_case_level_access_control(client, auth_headers, investigator2_headers):
    # investigator2 is assigned to C101 but not C204
    assert client.get("/api/cases/C101", headers=investigator2_headers).status_code == 200
    assert client.get("/api/cases/C204", headers=investigator2_headers).status_code == 403
    # investigator1 has access to both
    assert client.get("/api/cases/C204", headers=auth_headers).status_code == 200


def test_admin_bypasses_case_access(client, admin_headers):
    assert client.get("/api/cases/C204", headers=admin_headers).status_code == 200


def test_unknown_api_path_returns_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers.get("content-type", "").startswith("application/json")


def test_health_endpoint(client):
    assert client.get("/health").status_code == 200
