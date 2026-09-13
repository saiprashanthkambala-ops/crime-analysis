# Crime Analysis

**AI-Powered Criminal Network Analysis & Investigation Platform** (SIH26189)

Crime Analysis transforms fragmented investigation records (FIRs, CDRs, financial
transactions, CCTV reports, cases) into structured entities, dynamic
evidence-backed profiles, and candidate relationships — presented through an
interactive network and timeline for investigator review.

Core principle:

> **AI proposes → Evidence validates → Investigator decides.**

A relationship's *strength* reflects the weight of supporting evidence. It is
never a probability of guilt.

---

## What's implemented

| Area | Details |
| --- | --- |
| **Auth** | JWT login/logout, RBAC (`investigator`, `admin`), case-level access control |
| **Ingestion** | PDF (text + OCR fallback via Tesseract), CSV (CDR), JSON (transactions, CCTV), TXT. Async background processing with stage tracking (validating → parsing → ocr → extracting → normalizing → resolving → analyzing → completed/failed) |
| **Dataset importer** | Dedicated UI (`/import` or `/cases/:id/import`) for multi-file drag & drop import: per-file validation + pre-flight checks, CSV column mapping to canonical Crime Analysis fields (auto-detect + manual), content-hash duplicate detection, import history with statistics and one-click retry. Files flow through the single ingestion pipeline above |
| **Extraction** | People, phones, vehicles, bank accounts, locations, dates, times, calls, transactions, events — all with source provenance |
| **Normalization** | Phones, names, vehicles, accounts, dates, times — original value always preserved |
| **Entity resolution** | Conservative same-person clustering via name similarity + shared identifiers, with persisted explainability (merged variants + signals + confidence) |
| **Profiles** | Dynamic — only evidence-supported attributes; missing data = *unavailable* |
| **Relationships** | Modular multi-signal discovery (calls, transactions, location co-observation, shared identifiers) + evidence-strength scoring |
| **Explainability** | Every relationship shows *why*, its sources, temporal context, and uncertainties |
| **Evidence** | First-class records traceable to source document |
| **Timeline** | Known dates/times only; missing time = *unavailable* (never invented) |
| **Graph** | Interactive Cytoscape.js network (persons, phones, vehicles, accounts, locations, cases, events) with node-type filtering |
| **Search** | Global search by person / case / phone / vehicle / account / identifier |
| **Feedback** | Relevant / Incorrect / Needs Review (with note) — stored for controlled evaluation |
| **Audit** | Login, upload, search, views, feedback, admin actions |
| **Demo data** | Synthetic "Operation Red River" investigation (FIR + CDR + transactions + CCTV) |

---

## Tech stack

- **Frontend:** React 18 + Vite + React Router + Cytoscape.js
- **Backend:** Python + FastAPI
- **Database:** SQLAlchemy ORM. Defaults to **SQLite** with JSON columns that
  mirror the flexible Mongo-style profile documents from the PRD. MongoDB /
  Neo4j are swappable via environment variables (see below).
- **NLP/ML:** rule-based + deterministic extraction (dictionary + regex), with
  a modular signal-based relationship engine. Structured to accept spaCy /
  scikit-learn / transformers without changing the pipeline.
- **OCR:** Tesseract (auto-detected; falls back to direct text extraction).

---

## Quick start

### 1. Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On first startup the database is created and seeded with the synthetic demo.

### 2. Frontend (dev mode, optional)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api → :8000)
```

### 3. Production-style single server

```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

FastAPI serves the built React app; open http://localhost:8000.

> **Routing:** backend APIs are namespaced under `/api/*` (e.g. `/api/cases`,
> `/api/persons`, `/api/relationships`), while React routes live at the root
> (`/cases`, `/persons/:id`, …). Hard-refreshing any frontend route returns the
> React app, never raw API JSON.

### Demo credentials

| Role | Username | Password |
| --- | --- | --- |
| Investigator | `investigator1` | `investor1` |
| Investigator | `investigator2` | `investor2` |
| Admin | `admin` | `admin123` |

---

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///.../crime_analysis.db` | SQLAlchemy URL (set to a Mongo/Postgres URL to swap) |
| `JWT_SECRET` | dev secret | Token signing key — **set in production** |
| `JWT_EXPIRE_MINUTES` | `720` | Token lifetime |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` | empty | When set, enables the Neo4j graph store (currently the in-process projection is used) |
| `TESSERACT_CMD` | `tesseract` | OCR binary path |
| `MAX_UPLOAD_MB` | `25` | Maximum size of a single imported file |
| `AUTO_SEED` | `1` | Seed demo data when the DB is empty |

### Remote Neo4j (graph database)

The backend can additionally connect to a **remote** Neo4j instance
(SQLite remains the system of record). Copy `.env.example` to `.env`, fill in
`NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD`, and check connectivity:

```bash
curl http://localhost:8000/api/health/neo4j   # runs a real `RETURN 1` query
```

Full setup, security notes and troubleshooting: **[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)**.

## Dataset import

Import real investigation datasets through the importer UI (**Import Data** in the
navigation, or the **Import Dataset** button on a case) or the API:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/cases/{id}/imports/preflight` | Validate files *before* import: type/content sniffing, size, CSV/JSON structure, detected CSV columns + suggested mapping, duplicate check. Nothing is persisted. |
| `POST /api/cases/{id}/imports` | Import one or more files (multipart `files`, optional `mapping` JSON array aligned with the files). The whole batch is validated first — any invalid file rejects the batch without persisting anything. Accepted files are queued on the standard pipeline. |
| `GET /api/cases/{id}/imports` | Import history with per-file statistics, warnings, hash, mapping and uploader. |
| `POST /api/documents/{id}/retry` | Retry a failed import (source file is retained until a run completes). |
| `POST /api/cases/{id}/upload` | Legacy single-file upload (kept for API compatibility). |

Workflow: **select case → drop files → per-file validation shown inline (type, size,
content, structure, duplicates, OCR-needed) → optional CSV column mapping → import
with upload progress → live pipeline stages → history with stats/errors/retry**.

Supported formats: PDF (text layer first; Tesseract OCR fallback for scanned
documents), CSV (auto-detected CDR / transaction / person-record shapes), JSON
(arrays/objects of transaction, call, CCTV and event records), TXT.

Column mapping: Crime Analysis recognises canonical fields (caller/callee name+phone,
sender/receiver name+account, amount, transaction ID, person name, phone, vehicle,
account, location, date, time, timestamp) from many common header spellings
(`phone`/`mobile`/`phone_number`/`contact_number` → the same concept) and lets the
investigator re-map any CSV column before import. Original values and headers are
always preserved for provenance — nothing is overwritten or fabricated.

Duplicate protection: content is hashed (SHA-256) at upload; re-importing identical
content into the same case is rejected with a pointer to the existing document,
while identical filenames with different content, or identical content in a
*different* case, are allowed.

## Tests

---

## Project structure

```
backend/
  app/
    main.py            # FastAPI app + SPA serving
    config.py          # env-driven settings
    database.py        # engine / session
    models.py          # SQLAlchemy models
    security.py        # JWT + RBAC + audit helpers
    seed.py            # synthetic demo dataset
    routers/           # auth, data (cases/uploads), intelligence, admin
    services/
      extraction.py    # entity/event extraction (text, CSV, JSON)
      normalization.py # canonical value normalization
      resolution.py    # same-person resolution
      relationships.py # multi-signal relationship discovery + scoring
      timeline.py      # chronological timeline
      graph.py         # graph projection
      pipeline.py      # end-to-end ingestion pipeline
      profile.py       # dynamic profile assembly
frontend/
  src/
    pages/             # Login, Dashboard, Cases, Profile, Relationships, ...
    components/        # Layout, NetworkGraph, ui primitives
data/                  # (generated) synthetic source files
```

---

## Tests

```bash
source .venv/bin/activate
pip install pytest
cd backend
python -m pytest -q        # 50 tests: unit + auth/RBAC + ingestion + provenance + dataset import + E2E
```

---

## Design principles (enforced)

- Evidence over speculation
- Dynamic profiles over rigid forms
- AI-assisted discovery over autonomous judgement
- Source traceability over black-box results
- Missing data = **unknown** (never negative evidence)
- Never invent dates, times, or relationships
- The graph is a navigation layer, not a guilt engine
- A human always remains in the decision loop
