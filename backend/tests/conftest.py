import os
import tempfile

import pytest

# Use an isolated temporary database for tests (must be set before app import).
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["AUTO_SEED"] = "1"
os.environ["JWT_SECRET"] = "test-secret-key-that-is-long-enough-32-bytes"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    r = client.post("/api/auth/login", json={"username": "investigator1", "password": "investor1"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def investigator2_headers(client):
    r = client.post("/api/auth/login", json={"username": "investigator2", "password": "investor2"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
