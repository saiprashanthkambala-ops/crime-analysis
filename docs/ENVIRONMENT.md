# Environment configuration

This document explains every environment variable the Crime Analysis backend
reads, with a focus on the **remote Neo4j** connection introduced in Phase 1.

The application keeps **SQLite** as its system of record (cases, users,
documents, entities, relationships, evidence, timeline). Neo4j is a *remote
graph database* connected in addition to SQLite — it is optional at runtime:
when it is not configured or temporarily unreachable, every existing feature
keeps working and the Neo4j health endpoints report the situation.

```
React Frontend
      |
      v
FastAPI Backend
      |
      +--------------------+
      |                    |
      v                    v
   SQLite              Remote Neo4j
Existing data          Graph database
```

---

## 1. Quick start

```bash
# from the repository root
cp .env.example .env
# ... then edit .env and fill in the real values (never commit this file)
```

The backend loads `.env` from the **repository root** and from **`backend/`**
(root wins if both exist). Real environment variables always take precedence
over `.env` values, so production deployments configure everything through the
environment and never need a `.env` file at all.

---

## 2. Variables

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `DATABASE_URL` | no | `sqlite:///<backend>/crime_analysis.db` | SQLAlchemy URL of the application database (SQLite stays the system of record). |
| `JWT_SECRET` | yes in production | dev value | Token signing key. Change it for any real deployment. |
| `JWT_EXPIRE_MINUTES` | no | `720` | Access-token lifetime. |
| `NEO4J_URI` | to enable Neo4j | *(empty)* | Full connection URI of the remote Neo4j instance, e.g. `neo4j+s://xxxx.databases.neo4j.io`. |
| `NEO4J_USERNAME` | to enable Neo4j | *(empty)* | Neo4j user name (the default Neo4j user is `neo4j`). |
| `NEO4J_PASSWORD` | to enable Neo4j | *(empty)* | Password for the Neo4j user. **Secret — never commit it.** |
| `TESSERACT_CMD` | no | `tesseract` | OCR binary used by the document pipeline. |
| `MAX_UPLOAD_MB` | no | `25` | Maximum size of a single imported file. |
| `AUTO_SEED` | no | `1` | Seed the demo dataset when the database is empty. |

### Neo4j variables in detail

All **three** `NEO4J_*` variables must be set to enable the connection. The
empty defaults intentionally *disable* Neo4j — the application never guesses
or falls back to placeholder credentials. Missing variables are detected at
startup and reported by name, e.g.:

```
Neo4j disabled — configuration problem: Neo4j configuration is incomplete:
missing NEO4J_PASSWORD. Set the variable(s) in the environment or your .env
file (see docs/ENVIRONMENT.md).
```

`NEO4J_URI` must be the URI exactly as provided by your Neo4j provider,
including its scheme:

| Scheme | Transport | Typical use |
| --- | --- | --- |
| `neo4j+s://` | Routing, **TLS-encrypted** | Neo4j Aura and other hosted instances — the common case |
| `neo4j+ssc://` | Routing, TLS with self-signed certificate | Self-managed clusters |
| `neo4j://` | Routing, unencrypted | Trusted networks only |
| `bolt+s://` / `bolt+ssc://` / `bolt://` | Direct connection | Single-instance deployments |

> **Never downgrade a `+s` (encrypted) URI to a plain scheme** to "make it
> work" — the password would travel unencrypted. The backend keeps whatever
> scheme you configure.

---

## 3. How to obtain Neo4j connection information

For **Neo4j Aura** (Neo4j's managed cloud service):

1. Create/free-tier an instance in the [Aura console](https://console.neo4j.io).
2. When the instance is created, download the credentials file — it contains
   the generated password (shown only once; reset it in the console if lost).
3. Open the instance page and copy the **connection URI**
   (looks like `neo4j+s://xxxxxxxx.databases.neo4j.io`) — the `neo4j+s://`
   scheme means TLS is used automatically.
4. The username is `neo4j` unless you created another user.

For a **self-managed / company-hosted** Neo4j, ask your administrator for the
Bolt URI, username and password (and whether TLS is required — that decides
between `+s` / `+ssc` and plain schemes).

---

## 4. Configuring `.env`

1. Copy the template: `cp .env.example .env` (repo root, or `backend/`).
2. Fill in real values:

   ```
   NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=<the real password>
   ```

3. Start (or restart) the backend. Startup logs tell you what happened:
   - `Neo4j connected (connectivity check took NN ms).` — working.
   - `Neo4j not configured (...)` — variables missing; the app runs without it.
   - `Neo4j connection failed at startup (reason=...)` — configured but
     unreachable; the app still runs, see error table below.

### Why `.env` must not be committed

`.env` holds real credentials. Anyone with repository access (or any future
CI job that checks out the repo) would get access to your database. Git
history is effectively forever — a committed secret must be considered
compromised and rotated. For that reason `.gitignore` contains:

```
.env
.env.*
!.env.example
```

Only `.env.example` (placeholders, no real values) is tracked.

### How `.env.example` is used

It is the *documentation of the expected shape* of `.env`: copy it, fill in
real values, keep the copy local. When a new variable becomes supported in a
later phase, the example file is updated — never the real values.

---

## 5. Testing Neo4j connectivity

### Via the API

Start the backend, then:

```bash
# Basic app health — stays 200/"healthy" even when Neo4j is down
curl http://localhost:8000/health

# Dedicated Neo4j diagnostic — runs a real `RETURN 1` Cypher query
curl http://localhost:8000/api/health/neo4j
```

Responses:

| Neo4j state | `/health` | `/api/health/neo4j` |
| --- | --- | --- |
| Connected | `200 {"status": "healthy", "neo4j": {"status": "connected", "latency_ms": ...}}` | `200 {"status": "connected", "latency_ms": ...}` |
| Not configured | `200 {..., "neo4j": {"status": "not_configured", ...}}` | `200 {"status": "not_configured", ...}` |
| Configured but unreachable | `200 {..., "neo4j": {"status": "unavailable", ...}}` | `503 {"status": "unavailable", "reason": ..., "detail": ...}` |

The diagnostic **never** returns the password, username or connection URI.

### Via the test suite

The unit-test suite is fully offline (the Neo4j layer is exercised through
fakes). To additionally run the two live integration tests against your
configured remote instance:

```bash
cd backend
NEO4J_INTEGRATION_TEST=1 python -m pytest tests/test_neo4j.py -v
```

With the flag set, the tests read `NEO4J_URI` / `NEO4J_USERNAME` /
`NEO4J_PASSWORD` from your environment / `.env` and execute a real
`RETURN 1 AS ok` round-trip. Without the flag they are skipped, so CI never
depends on a private Neo4j instance.

---

## 6. Common connection errors

| Symptom (`reason` in the diagnostic / startup log) | Cause | Fix |
| --- | --- | --- |
| `not_configured` | One or more `NEO4J_*` variables are empty. | Set all three in the environment or `.env`. |
| `auth_error` | Wrong username or password. | Verify `NEO4J_USERNAME` / `NEO4J_PASSWORD`; reset the password in your Neo4j provider's console if needed. |
| `unavailable` | Host down, wrong URI, network/firewall block, or the connection timed out. | Check `NEO4J_URI` spelling and that the host/port are reachable from this machine (corporate VPN/proxy?). |
| `Neo4j configuration is incomplete / invalid` (startup log) | Missing variables, URI without a scheme, or an unsupported scheme. | Use the full URI from your provider, e.g. `neo4j+s://xxxx.databases.neo4j.io`. |
| Certificate / TLS warnings in `detail` | Self-signed certificate with a `+s` URI. | Use `neo4j+ssc://` (or install a proper certificate). |
| Works locally but not from a server | The server cannot reach the Neo4j host (egress rules / IP allow-list on the Neo4j side). | Allow-list the server's IP in your Neo4j provider's network settings. |

A single connection attempt is capped at 5 seconds, so an unreachable
database can never hang the health endpoints.

---

## 7. Local development vs. remote Neo4j

- **The project's Neo4j is remote.** Configure it with the three `NEO4J_*`
  variables as described above. Nothing in the backend assumes a local Neo4j
  or contains default credentials.
- `docker-compose.yml` optionally starts a **local** Neo4j container for
  experimentation (uncomment the `NEO4J_*` lines in the `app` service and
  point them at `bolt://neo4j:7687`). That container is completely separate
  from your remote instance — useful for offline experiments, irrelevant for
  the normal setup.
- With no Neo4j configured at all, the application is fully functional on
  SQLite and the existing in-process graph projection.

---

## 8. Security rules (summary)

- Never commit `.env` (git-ignored) and never paste real credentials into
  code, documentation, `.env.example`, tests, issues or chat.
- The backend never logs `NEO4J_PASSWORD` and never returns it (or the
  username/URI) from an API. Error messages are reduced to safe
  classifications ("authentication failed", "unavailable", ...) and driver
  error text is scrubbed of credentials before it is logged.
- Real environment variables beat `.env` values — deployment platforms can
  inject secrets without touching files.
