"""Neo4j connection infrastructure (Phase 1).

This module owns everything needed to talk to the project's REMOTE Neo4j
instance: configuration validation, driver lifecycle, connectivity
verification and parameterized query execution.

It deliberately contains no graph business logic — no node/relationship
creation, no synchronization with the SQLite data, no analytics. Those
belong to later phases and will build on top of ``run_read_query``.

Security notes
--------------
* Credentials come from ``settings`` (environment variables / local .env) and
  are never logged, returned or embedded in error messages.
* Every error message that can leave this module passes through
  :func:`redact_secrets`, which strips credential material from URLs and
  free-form text.
"""
import logging
import re
import threading
import time
from typing import Any, Optional

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    DriverError,
    Neo4jError,
    ServiceUnavailable,
    SessionExpired,
)

from ..config import settings

logger = logging.getLogger(__name__)

# Trivial query used to prove connection + session + execution + retrieval.
# A created driver object alone proves nothing — a real round-trip must
# succeed before Neo4j is reported as connected.
CONNECTIVITY_QUERY = "RETURN 1 AS ok"

# Upper bound for a single connection attempt, so health endpoints stay
# responsive when the remote instance is unreachable.
CONNECTION_TIMEOUT_SECONDS = 5.0

# Schemes accepted by the Neo4j driver. The ``+s`` / ``+ssc`` variants are the
# TLS-encrypted transports used by remote instances such as Neo4j Aura — a
# secure URI must never be downgraded to a plain one.
SUPPORTED_SCHEMES = ("neo4j", "neo4j+s", "neo4j+ssc", "bolt", "bolt+s", "bolt+ssc")


# --------------------------------------------------------------------------- #
# Errors (safe for logs and API responses — never contain credentials)
# --------------------------------------------------------------------------- #
class Neo4jConfigError(RuntimeError):
    """Neo4j settings are missing or invalid. Mentions variable names only."""


class Neo4jConnectionError(RuntimeError):
    """The remote Neo4j database could not be reached or queried.

    ``message`` and ``detail`` are safe to log and to return from an API:
    they are built from fixed strings or pass through :func:`redact_secrets`.
    ``reason`` is a stable machine-readable classification, e.g.
    ``auth_error``, ``unavailable``, ``connection_error``, ``query_error``.
    """

    def __init__(self, message: str, *, reason: str = "unknown", detail: str = ""):
        super().__init__(message)
        self.reason = reason
        self.detail = detail


# --------------------------------------------------------------------------- #
# Secret redaction
# --------------------------------------------------------------------------- #
_URL_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*)://[^/@\s:]+:[^/@\s]+@")


def redact_secrets(text: Any) -> str:
    """Return ``text`` with credential material removed.

    Strips ``user:password`` segments embedded in URLs and replaces any
    occurrence of the configured Neo4j password with ``***``. Used on every
    error string before it is logged or returned.
    """
    redacted = _URL_CREDENTIALS.sub(r"\1://***@", str(text))
    password = settings.NEO4J_PASSWORD
    if password:
        redacted = redacted.replace(password, "***")
    return redacted


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def is_configured() -> bool:
    """True only when all three Neo4j variables have a non-empty value."""
    return all(
        value.strip()
        for value in (settings.NEO4J_URI, settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
    )


def validate_config() -> None:
    """Raise :class:`Neo4jConfigError` with a clear, secret-free description.

    Missing variables are reported by name; the URI must carry a supported
    scheme so obvious mistakes surface as configuration errors instead of
    cryptic connection failures later on.
    """
    missing = [
        name
        for name, value in (
            ("NEO4J_URI", settings.NEO4J_URI),
            ("NEO4J_USERNAME", settings.NEO4J_USERNAME),
            ("NEO4J_PASSWORD", settings.NEO4J_PASSWORD),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise Neo4jConfigError(
            "Neo4j configuration is incomplete: missing "
            + ", ".join(missing)
            + ". Set the variable(s) in the environment or your .env file "
            "(see docs/ENVIRONMENT.md)."
        )

    uri = settings.NEO4J_URI.strip()
    if "://" not in uri:
        raise Neo4jConfigError(
            "NEO4J_URI must be a full connection URI including its scheme, "
            "for example neo4j+s://<your-instance>.databases.neo4j.io."
        )
    scheme = uri.split("://", 1)[0].lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise Neo4jConfigError(
            "NEO4J_URI scheme {!r} is not supported. Use one of: {}.".format(
                scheme, ", ".join(SUPPORTED_SCHEMES)
            )
        )


# --------------------------------------------------------------------------- #
# Driver lifecycle
# --------------------------------------------------------------------------- #
_driver: Optional[Driver] = None
_driver_lock = threading.Lock()


def get_driver() -> Driver:
    """Return the shared process-wide driver, creating it on first use.

    The official Neo4j driver is thread-safe and pools its own connections,
    so exactly one driver is reused for the lifetime of the application —
    never one per request.
    """
    global _driver
    if _driver is not None:
        return _driver
    with _driver_lock:
        if _driver is None:
            _driver = _create_driver()
    return _driver


def _create_driver() -> Driver:
    validate_config()
    try:
        return GraphDatabase.driver(
            settings.NEO4J_URI.strip(),
            auth=(settings.NEO4J_USERNAME.strip(), settings.NEO4J_PASSWORD),
            connection_timeout=CONNECTION_TIMEOUT_SECONDS,
        )
    except ConfigurationError as exc:
        # Malformed URI / unsupported scheme. The driver message contains no
        # credentials, but redact defensively anyway.
        raise Neo4jConfigError("Invalid NEO4J_URI: " + redact_secrets(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive catch-all
        raise Neo4jConnectionError(
            "The Neo4j driver could not be created.",
            reason="config_error",
            detail=redact_secrets(exc),
        ) from exc


def close_driver() -> None:
    """Close the shared driver (application shutdown). Idempotent."""
    global _driver
    with _driver_lock:
        driver, _driver = _driver, None
    if driver is None:
        return
    try:
        driver.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Error while closing the Neo4j driver: %s", redact_secrets(exc))


def init_neo4j() -> None:
    """Prepare the Neo4j driver during application startup. Never raises.

    A missing or unreachable Neo4j must not take the whole application down —
    SQLite and every existing API keep working. The situation is logged with
    a safe diagnostic instead, and Neo4j health endpoints report
    ``unavailable`` until the connection recovers.
    """
    if not is_configured():
        logger.info(
            "Neo4j not configured (NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD) — "
            "continuing with SQLite and the in-process graph projection."
        )
        return
    try:
        get_driver()
    except Neo4jConfigError as exc:
        logger.error("Neo4j disabled — configuration problem: %s", exc)
        return
    try:
        info = verify_connectivity()
    except Neo4jConnectionError as exc:
        logger.warning(
            "Neo4j connection failed at startup (reason=%s): %s. The API keeps "
            "running; Neo4j reports 'unavailable' until the connection recovers.",
            exc.reason,
            exc,
        )
        if exc.detail:
            logger.warning("Neo4j startup failure detail: %s", exc.detail)
        return
    logger.info("Neo4j connected (connectivity check took %.0f ms).", info["latency_ms"])


# --------------------------------------------------------------------------- #
# Query execution (foundation for later phases)
# --------------------------------------------------------------------------- #
def run_read_query(
    query: str, parameters: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    """Execute a read-only Cypher query and return its rows as dicts.

    ``query`` must reference values through ``$parameter`` placeholders;
    ``parameters`` are passed to the driver separately and are never
    interpolated into the Cypher text.
    """
    driver = get_driver()
    try:
        with driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    except AuthError as exc:
        raise Neo4jConnectionError(
            "Neo4j authentication failed (check NEO4J_USERNAME / NEO4J_PASSWORD).",
            reason="auth_error",
            detail=redact_secrets(exc),
        ) from exc
    except (ServiceUnavailable, SessionExpired) as exc:
        raise Neo4jConnectionError(
            "Neo4j is unavailable (host down, unreachable or the connection timed out).",
            reason="unavailable",
            detail=redact_secrets(exc),
        ) from exc
    except DriverError as exc:
        raise Neo4jConnectionError(
            "Neo4j connection error.",
            reason="connection_error",
            detail=redact_secrets(exc),
        ) from exc
    except Neo4jError as exc:
        # Server-side Cypher failures (e.g. syntax errors) — classified
        # separately from connection problems.
        raise Neo4jConnectionError(
            "Neo4j rejected the query.",
            reason="query_error",
            detail=redact_secrets(exc),
        ) from exc


def verify_connectivity() -> dict[str, Any]:
    """Prove the remote database works by executing a real Cypher query.

    Returns ``{"status": "connected", "latency_ms": <float>}`` on success;
    raises :class:`Neo4jConfigError` or :class:`Neo4jConnectionError`
    otherwise.
    """
    started = time.perf_counter()
    rows = run_read_query(CONNECTIVITY_QUERY)
    latency_ms = (time.perf_counter() - started) * 1000.0
    if not rows or rows[0].get("ok") != 1:
        raise Neo4jConnectionError(
            "Neo4j connectivity check returned an unexpected result.",
            reason="connection_error",
            detail="query {!r} returned {!r}".format(CONNECTIVITY_QUERY, rows),
        )
    return {"status": "connected", "latency_ms": round(latency_ms, 1)}


def neo4j_status() -> dict[str, Any]:
    """Snapshot of Neo4j connectivity, safe to return from an API endpoint."""
    if not is_configured():
        return {
            "status": "not_configured",
            "detail": (
                "Neo4j is not configured. Set NEO4J_URI, NEO4J_USERNAME and "
                "NEO4J_PASSWORD (see docs/ENVIRONMENT.md)."
            ),
        }
    try:
        info = verify_connectivity()
    except Neo4jConnectionError as exc:
        return {"status": "unavailable", "reason": exc.reason, "detail": str(exc)}
    return {"status": "connected", "latency_ms": info["latency_ms"]}
