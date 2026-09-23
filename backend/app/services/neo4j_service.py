"""Neo4j connection infrastructure and parameterized Cypher execution."""
import logging
import re
import threading
import time
from typing import Any, Optional

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, ConfigurationError, DriverError, Neo4jError, ServiceUnavailable, SessionExpired
from ..config import settings

logger = logging.getLogger(__name__)
CONNECTIVITY_QUERY = "RETURN 1 AS ok"
CONNECTION_TIMEOUT_SECONDS = 5.0
SUPPORTED_SCHEMES = ("neo4j", "neo4j+s", "neo4j+ssc", "bolt", "bolt+s", "bolt+ssc")

class Neo4jConfigError(RuntimeError):
    """Neo4j settings are missing or invalid."""

class Neo4jConnectionError(RuntimeError):
    """Neo4j could not be reached or rejected a query."""
    def __init__(self, message: str, *, reason: str = "unknown", detail: str = ""):
        super().__init__(message)
        self.reason = reason
        self.detail = detail

_URL_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*)://[^/@\s:]+:[^/@\s]+@")

def redact_secrets(text: Any) -> str:
    redacted = _URL_CREDENTIALS.sub(r"\1://***@", str(text))
    if settings.NEO4J_PASSWORD:
        redacted = redacted.replace(settings.NEO4J_PASSWORD, "***")
    return redacted

def is_configured() -> bool:
    return all(v.strip() for v in (settings.NEO4J_URI, settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))

def validate_config() -> None:
    missing = [name for name, value in (("NEO4J_URI", settings.NEO4J_URI), ("NEO4J_USERNAME", settings.NEO4J_USERNAME), ("NEO4J_PASSWORD", settings.NEO4J_PASSWORD)) if not (value or "").strip()]
    if missing:
        raise Neo4jConfigError("Neo4j configuration is incomplete: missing " + ", ".join(missing) + ".")
    uri = settings.NEO4J_URI.strip()
    if "://" not in uri:
        raise Neo4jConfigError("NEO4J_URI must be a full Neo4j connection URI.")
    scheme = uri.split("://", 1)[0].lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise Neo4jConfigError("NEO4J_URI scheme {!r} is not supported.".format(scheme))

_driver: Optional[Driver] = None
_driver_lock = threading.Lock()

def get_driver() -> Driver:
    global _driver
    if _driver is None:
        with _driver_lock:
            if _driver is None:
                _driver = _create_driver()
    return _driver

def _create_driver() -> Driver:
    validate_config()
    try:
        return GraphDatabase.driver(settings.NEO4J_URI.strip(), auth=(settings.NEO4J_USERNAME.strip(), settings.NEO4J_PASSWORD), connection_timeout=CONNECTION_TIMEOUT_SECONDS)
    except ConfigurationError as exc:
        raise Neo4jConfigError("Invalid NEO4J_URI: " + redact_secrets(exc)) from exc
    except Exception as exc:
        raise Neo4jConnectionError("The Neo4j driver could not be created.", reason="config_error", detail=redact_secrets(exc)) from exc

def close_driver() -> None:
    global _driver
    with _driver_lock:
        driver, _driver = _driver, None
    if driver is not None:
        try:
            driver.close()
        except Exception as exc:
            logger.warning("Error while closing the Neo4j driver: %s", redact_secrets(exc))

def init_neo4j() -> None:
    if not is_configured():
        logger.info("Neo4j is not configured; continuing with the SQL graph layer.")
        return
    try:
        get_driver()
        status = neo4j_status()
        if status.get("connected"):
            logger.info("Neo4j connected.")
        else:
            logger.warning("Neo4j startup check failed: %s", status.get("detail", "unavailable"))
    except (Neo4jConfigError, Neo4jConnectionError) as exc:
        logger.warning("Neo4j startup check failed: %s", exc)
    except Exception as exc:
        logger.warning("Neo4j startup check failed: %s", redact_secrets(exc))

def _run_query(query: str, parameters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    def execute(driver):
        with driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    driver = get_driver()
    try:
        return execute(driver)
    except AuthError as exc:
        raise Neo4jConnectionError("Neo4j authentication failed (check NEO4J_USERNAME / NEO4J_PASSWORD).", reason="auth_error", detail=redact_secrets(exc)) from exc
    except ValueError as exc:
        raise Neo4jConnectionError("Neo4j is unavailable (address resolution failed): " + redact_secrets(exc), reason="unavailable", detail=redact_secrets(exc)) from exc
    except (ServiceUnavailable, SessionExpired, DriverError, OSError, TimeoutError, ConnectionError) as exc:
        # Aura/cloud connections can be reset while a pooled driver still
        # points at a dead connection. Recreate the driver once and retry.
        logger.warning("Neo4j connection failure; recreating driver once: %s", redact_secrets(exc))
        close_driver()
        try:
            return execute(get_driver())
        except (ServiceUnavailable, SessionExpired, ValueError) as retry_exc:
            raise Neo4jConnectionError(
                "Neo4j is unavailable.",
                reason="unavailable",
                detail=redact_secrets(retry_exc),
            ) from retry_exc
        except DriverError as retry_exc:
            reason = "unavailable" if isinstance(exc, (ServiceUnavailable, SessionExpired)) or isinstance(retry_exc, ServiceUnavailable) else "connection_error"
            raise Neo4jConnectionError(
                "Neo4j connection error.",
                reason=reason,
                detail=redact_secrets(retry_exc),
            ) from retry_exc
        except Exception as retry_exc:
            reason = "unavailable" if isinstance(exc, (ServiceUnavailable, SessionExpired)) else "connection_error"
            raise Neo4jConnectionError(
                "Neo4j connection error after retry.",
                reason=reason,
                detail=redact_secrets(retry_exc),
            ) from retry_exc
    except Neo4jError as exc:
        raise Neo4jConnectionError("Neo4j rejected the query.", reason="query_error", detail=redact_secrets(exc)) from exc
    except Exception as exc:
        raise Neo4jConnectionError("Neo4j error: " + redact_secrets(exc), reason="connection_error", detail=redact_secrets(exc)) from exc

def run_read_query(query: str, parameters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    return _run_query(query, parameters)

def run_write_query(query: str, parameters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    return _run_query(query, parameters)

def verify_connectivity() -> dict[str, Any]:
    started = time.perf_counter()
    rows = run_read_query(CONNECTIVITY_QUERY)
    latency_ms = (time.perf_counter() - started) * 1000.0
    if not rows or rows[0].get("ok") != 1:
        raise Neo4jConnectionError("Neo4j connectivity check returned an unexpected result.", reason="connection_error")
    return {"status": "connected", "latency_ms": round(latency_ms, 1)}

def neo4j_status() -> dict[str, Any]:
    if not is_configured():
        return {"connected": False, "status": "not_configured", "detail": "Set NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD."}
    try:
        info = verify_connectivity()
        return {"connected": True, "status": "connected", "latency_ms": info["latency_ms"]}
    except Neo4jConnectionError as exc:
        return {"connected": False, "status": "unavailable", "reason": exc.reason, "detail": str(exc)}
    except Exception as exc:
        return {"connected": False, "status": "unavailable", "reason": "connection_error", "detail": redact_secrets(exc)}
