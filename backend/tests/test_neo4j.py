"""Phase 1 — Neo4j connection infrastructure tests.

All tests run offline by default: the driver/session layer is exercised
through fakes, so the suite never needs a reachable Neo4j server and never
sees real credentials.

To additionally run the live integration tests against your configured
remote Neo4j (values come from your environment / .env):

    NEO4J_INTEGRATION_TEST=1 python -m pytest tests/test_neo4j.py -v
"""
import os

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.config import Settings, settings
from app.services import neo4j_service
from app.services.neo4j_service import Neo4jConfigError, Neo4jConnectionError

UNIT_TEST_URI = "neo4j+s://unit-test.example.databases.neo4j.io"
UNIT_TEST_PASSWORD = "unit-test-password-do-not-print"

INTEGRATION_ENABLED = os.environ.get("NEO4J_INTEGRATION_TEST", "") == "1"


# --------------------------------------------------------------------- helpers
def configure_neo4j(
    monkeypatch,
    *,
    uri=UNIT_TEST_URI,
    username="neo4j",
    password=UNIT_TEST_PASSWORD,
):
    """Point the settings singleton at harmless unit-test values."""
    monkeypatch.setattr(settings, "NEO4J_URI", uri)
    monkeypatch.setattr(settings, "NEO4J_USERNAME", username)
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", password)


@pytest.fixture(autouse=True)
def _reset_driver_after_each_test():
    yield
    neo4j_service.close_driver()


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def data(self):
        return dict(self._data)


class FakeResult:
    def __init__(self, rows):
        self._rows = [FakeRecord(row) for row in rows]

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, driver):
        self._driver = driver
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, parameters=None):
        self.queries.append((query, dict(parameters or {})))
        if self._driver.error is not None:
            raise self._driver.error
        return FakeResult(self._driver.rows)


class FakeDriver:
    """Minimal neo4j.Driver stand-in — no network involved."""

    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else [{"ok": 1}]
        self.error = error
        self.sessions = []
        self.closed = False

    def session(self):
        session = FakeSession(self)
        self.sessions.append(session)
        return session

    def close(self):
        self.closed = True


# ------------------------------------------------------------ TEST A: loading
def test_settings_load_neo4j_values_from_environment(monkeypatch):
    """TEST A — Neo4j configuration is loaded correctly from the environment."""
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://env-test.example.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "from-environment")
    fresh = Settings()
    assert fresh.NEO4J_URI == "neo4j+s://env-test.example.databases.neo4j.io"
    assert fresh.NEO4J_USERNAME == "neo4j"
    assert fresh.NEO4J_PASSWORD == "from-environment"


# ------------------------------------------- TEST B/C/D: missing variables
def test_missing_neo4j_uri_is_detected(monkeypatch):
    """TEST B — a missing NEO4J_URI is reported as a configuration error."""
    configure_neo4j(monkeypatch, uri="")
    with pytest.raises(Neo4jConfigError, match="NEO4J_URI"):
        neo4j_service.validate_config()


def test_missing_neo4j_username_is_detected(monkeypatch):
    """TEST C — a missing NEO4J_USERNAME is reported as a configuration error."""
    configure_neo4j(monkeypatch, username="")
    with pytest.raises(Neo4jConfigError, match="NEO4J_USERNAME"):
        neo4j_service.validate_config()


def test_missing_neo4j_password_is_detected(monkeypatch):
    """TEST D — a missing NEO4J_PASSWORD is reported as a configuration error."""
    configure_neo4j(monkeypatch, password="")
    with pytest.raises(Neo4jConfigError, match="NEO4J_PASSWORD"):
        neo4j_service.validate_config()


def test_all_missing_variables_are_reported_together(monkeypatch):
    configure_neo4j(monkeypatch, uri="", username="", password="")
    with pytest.raises(Neo4jConfigError) as exc_info:
        neo4j_service.validate_config()
    message = str(exc_info.value)
    assert "NEO4J_URI" in message
    assert "NEO4J_USERNAME" in message
    assert "NEO4J_PASSWORD" in message
    # Variable names only — never their values.
    assert UNIT_TEST_PASSWORD not in message


@pytest.mark.parametrize(
    "bad_uri",
    [
        "your-instance.databases.neo4j.io",  # no scheme
        "https://your-instance.databases.neo4j.io",  # unsupported scheme
    ],
)
def test_invalid_neo4j_uri_is_detected(monkeypatch, bad_uri):
    configure_neo4j(monkeypatch, uri=bad_uri)
    with pytest.raises(Neo4jConfigError):
        neo4j_service.validate_config()


# ------------------------------------------------- TEST E: driver creation
def test_driver_is_created_and_reused(monkeypatch):
    """TEST E — a driver is created from valid config and reused (singleton).

    Driver construction in the official Neo4j driver is lazy, so this makes
    no network call.
    """
    configure_neo4j(monkeypatch)
    driver = neo4j_service.get_driver()
    assert driver is not None
    assert neo4j_service.get_driver() is driver


def test_get_driver_without_configuration_fails(monkeypatch):
    configure_neo4j(monkeypatch, uri="", username="", password="")
    with pytest.raises(Neo4jConfigError):
        neo4j_service.get_driver()


# ------------------------------------------- TEST F: connectivity checks
def test_verify_connectivity_executes_a_real_query(monkeypatch):
    """TEST F — the check runs an actual Cypher round-trip, not just a
    driver-object check, and reports the latency."""
    fake = FakeDriver(rows=[{"ok": 1}])
    monkeypatch.setattr(neo4j_service, "_driver", fake)
    info = neo4j_service.verify_connectivity()
    assert info["status"] == "connected"
    assert isinstance(info["latency_ms"], float)
    assert info["latency_ms"] >= 0
    # The connectivity query really went through a session.
    assert fake.sessions[0].queries == [("RETURN 1 AS ok", {})]


def test_verify_connectivity_rejects_unexpected_results(monkeypatch):
    fake = FakeDriver(rows=[{"ok": 42}])
    monkeypatch.setattr(neo4j_service, "_driver", fake)
    with pytest.raises(Neo4jConnectionError):
        neo4j_service.verify_connectivity()


# ------------------------------------------------- TEST G: Cypher queries
def test_simple_cypher_query_returns_expected_result(monkeypatch):
    """TEST G — a simple parameterized Cypher query returns its result."""
    fake = FakeDriver(rows=[{"result": 1}])
    monkeypatch.setattr(neo4j_service, "_driver", fake)
    rows = neo4j_service.run_read_query(
        "RETURN $expected AS result", parameters={"expected": 1}
    )
    assert rows == [{"result": 1}]
    # Values travel as parameters — never interpolated into the Cypher text.
    query, parameters = fake.sessions[0].queries[0]
    assert "$expected" in query
    assert "1" not in query.split("AS")[0]
    assert parameters == {"expected": 1}


def test_run_read_query_defaults_to_empty_parameters(monkeypatch):
    fake = FakeDriver(rows=[{"ok": 1}])
    monkeypatch.setattr(neo4j_service, "_driver", fake)
    rows = neo4j_service.run_read_query("RETURN 1 AS ok")
    assert rows == [{"ok": 1}]
    assert fake.sessions[0].queries == [("RETURN 1 AS ok", {})]


# --------------------------------------- TEST H: failures stay secret-free
def test_invalid_credentials_do_not_expose_the_password(monkeypatch):
    """TEST H — auth failures are classified without leaking the password,
    even when the underlying error message itself contains it."""
    secret = "super-secret-password-never-log-me"
    configure_neo4j(monkeypatch, password=secret)
    error = AuthError(
        "authentication failed for 'neo4j' with password "
        f"'{secret}' at neo4j+s://neo4j:{secret}@remote.example.databases.neo4j.io:7687"
    )
    monkeypatch.setattr(neo4j_service, "_driver", FakeDriver(error=error))

    with pytest.raises(Neo4jConnectionError) as exc_info:
        neo4j_service.verify_connectivity()

    assert exc_info.value.reason == "auth_error"
    assert secret not in str(exc_info.value)
    assert secret not in exc_info.value.detail


def test_unavailable_errors_are_classified_safely(monkeypatch):
    error = ServiceUnavailable(
        "Failed to establish connection to neo4j+ssc://neo4j:leaked@10.0.0.1:7687"
    )
    monkeypatch.setattr(neo4j_service, "_driver", FakeDriver(error=error))
    with pytest.raises(Neo4jConnectionError) as exc_info:
        neo4j_service.verify_connectivity()
    assert exc_info.value.reason == "unavailable"
    assert "leaked" not in str(exc_info.value)
    assert "leaked" not in exc_info.value.detail


def test_redact_secrets_strips_url_credentials_and_passwords(monkeypatch):
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "s3cret-pw")
    redacted = neo4j_service.redact_secrets(
        "neo4j+s://neo4j:s3cret-pw@db.example.com:7687"
    )
    assert redacted == "neo4j+s://***@db.example.com:7687"
    assert neo4j_service.redact_secrets("boom: s3cret-pw is wrong") == "boom: *** is wrong"


# ---------------------------------------------------- lifecycle / status
def test_init_neo4j_never_raises_when_neo4j_is_unreachable(monkeypatch):
    configure_neo4j(monkeypatch)

    def _fail():
        raise Neo4jConnectionError(
            "Neo4j is unavailable (host down, unreachable or the connection timed out).",
            reason="unavailable",
            detail="redacted detail",
        )

    monkeypatch.setattr(neo4j_service, "verify_connectivity", _fail)
    neo4j_service.init_neo4j()  # graceful degradation — must not raise


def test_init_neo4j_is_a_noop_when_not_configured(monkeypatch):
    configure_neo4j(monkeypatch, uri="", username="", password="")

    def _fail():
        raise AssertionError("connectivity must not be probed when unconfigured")

    monkeypatch.setattr(neo4j_service, "verify_connectivity", _fail)
    neo4j_service.init_neo4j()  # must not raise and must not probe


def test_close_driver_closes_and_is_idempotent(monkeypatch):
    fake = FakeDriver()
    monkeypatch.setattr(neo4j_service, "_driver", fake)
    neo4j_service.close_driver()
    assert fake.closed is True
    assert neo4j_service._driver is None
    neo4j_service.close_driver()  # second call is a no-op


def test_neo4j_status_reports_not_configured_without_secrets():
    status = neo4j_service.neo4j_status()
    assert status["status"] == "not_configured"
    assert "NEO4J_URI" in status["detail"]
    assert UNIT_TEST_PASSWORD not in str(status)


# ------------------------------------------------------- API endpoints
def test_health_endpoint_stays_healthy_and_reports_neo4j(client):
    """The existing contract is preserved: status stays 'healthy'; Neo4j is
    reported separately and never makes the app itself unhealthy."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["neo4j"]["status"] == "not_configured"  # hermetic unit-test env


def test_neo4j_diagnostic_endpoint_when_not_configured(client):
    r = client.get("/api/health/neo4j")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_configured"
    assert "NEO4J_URI" in body["detail"]


def test_neo4j_diagnostic_endpoint_when_connected(client, monkeypatch):
    configure_neo4j(monkeypatch)
    monkeypatch.setattr(neo4j_service, "_driver", FakeDriver(rows=[{"ok": 1}]))
    r = client.get("/api/health/neo4j")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "connected"
    assert isinstance(body["latency_ms"], (int, float))


def test_neo4j_diagnostic_endpoint_masks_credentials(client, monkeypatch):
    """A failing connection yields 503 — and the password never appears in the
    response, while /health keeps answering 200 'healthy'."""
    secret = "super-secret-password-never-log-me"
    configure_neo4j(monkeypatch, password=secret)
    error = AuthError(f"authentication failed, password was '{secret}'")
    monkeypatch.setattr(neo4j_service, "_driver", FakeDriver(error=error))

    r = client.get("/api/health/neo4j")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "auth_error"
    assert secret not in r.text

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["neo4j"]["status"] == "unavailable"
    assert secret not in health.text


def test_neo4j_endpoints_are_not_blocked_by_auth(client):
    """Diagnostics are unauthenticated by design (ops probes), like /health."""
    assert client.get("/api/health/neo4j").status_code == 200


# ------------------------------------------------- live integration tests
@pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="live Neo4j integration test — set NEO4J_INTEGRATION_TEST=1 with "
    "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD configured to enable",
)
def test_live_remote_neo4j_connectivity_and_query():
    """TEST F+G against the real remote database (opt-in)."""
    assert neo4j_service.is_configured(), (
        "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD must be set (e.g. in .env)"
    )
    info = neo4j_service.verify_connectivity()
    assert info["status"] == "connected"
    rows = neo4j_service.run_read_query(
        "RETURN $expected AS result", parameters={"expected": 1}
    )
    assert rows == [{"result": 1}]


@pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="live Neo4j integration test — set NEO4J_INTEGRATION_TEST=1 with "
    "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD configured to enable",
)
def test_live_health_endpoint_reports_connected(client):
    r = client.get("/api/health/neo4j")
    assert r.status_code == 200
    assert r.json()["status"] == "connected"
