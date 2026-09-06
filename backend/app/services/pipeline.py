"""End-to-end ingestion + analysis pipeline.

process_document() parses an uploaded file, validates it, extracts
entities/events, persists them with provenance, then triggers recompute_case()
which (re)builds persons, profiles, relationships and evidence for the whole
case. All import files — including retries — flow through this single pipeline;
there is no parallel ingestion path.

Stages follow the PRD:
    validating -> parsing|ocr_processing -> extracting -> normalizing ->
    resolving -> analyzing -> completed|failed
"""
import csv
import io
import json
import logging
import shutil
import subprocess
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings, DATA_DIR
from ..models import (AuditLog, Document, Entity, Event, Evidence,
                      Person, ProcessingJob, Relationship)
from .dataset_import import validate_file
from .extraction import extract_text, extract_csv_rows, extract_json_records
from .normalization import normalize_value, normalize_name
from .resolution import resolve_mentions
from .relationships import discover_relationships

logger = logging.getLogger("crimelink.pipeline")

PDF = "pdf"
CSV = "csv"
JSON = "json"
TXT = "txt"


def detect_type(filename, content):
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return PDF
    if name.endswith(".csv"):
        return CSV
    if name.endswith(".json"):
        return JSON
    if name.endswith(".txt") or name.endswith(".text"):
        return TXT
    # content sniffing
    head = content[:256].lstrip()
    if head.startswith((b"{", b"[")):
        return JSON
    return TXT


def _extract_pdf_text(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = [p.extract_text() or "" for p in reader.pages]
    return "\n".join(pages)


def _ocr_text(content):
    """Run Tesseract OCR when available; returns (text, used_ocr)."""
    if not shutil.which(settings.TESSERACT_CMD):
        return "", False
    try:
        proc = subprocess.run(
            [settings.TESSERACT_CMD, "stdin", "stdout"],
            input=content, capture_output=True, timeout=60,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", "ignore"), True
    except Exception:  # noqa: BLE001 - OCR is best-effort
        logger.exception("OCR subprocess failed")
    return "", False


def extract_document_content(filename, content):
    """Return (text, file_type, needs_ocr)."""
    ftype = detect_type(filename, content)
    if ftype == PDF:
        text = _extract_pdf_text(content)
        needs_ocr = False
        if not text.strip():
            text, needs_ocr = _ocr_text(content)
        return text, ftype, needs_ocr
    if ftype == CSV:
        return content.decode("utf-8", "ignore"), ftype, False
    if ftype == JSON:
        return content.decode("utf-8", "ignore"), ftype, False
    # TXT / fallback
    try:
        return content.decode("utf-8", "ignore"), TXT, False
    except Exception:  # noqa: BLE001
        return content.decode("latin-1", "ignore"), TXT, False


def _persist_entities(db, bundle, document, case_id):
    # identifier entities first
    for e in bundle.get("entities", []):
        etype = e["type"]
        nv = normalize_value(etype, e.get("value"))
        if not nv:
            continue
        existing = (
            db.query(Entity)
            .filter_by(entity_type=etype, normalized_value=nv, case_id=case_id)
            .first()
        )
        if existing:
            continue
        db.add(Entity(
            entity_type=etype,
            original_value=str(e.get("value")),
            normalized_value=nv,
            confidence=e.get("confidence", 1.0),
            extraction_method=e.get("method", "unknown"),
            source_document_id=document.id,
            source_reference=e.get("source_ref"),
            case_id=case_id,
            observed_date=e.get("date"),
            observed_time=e.get("time"),
            meta={"record_index": e.get("row")} if e.get("row") else None,
        ))
    # person mention entities
    for m in bundle.get("mentions", []):
        name = m.get("name")
        if not name:
            continue
        nv = normalize_name(name)
        ids = m.get("identifiers", {})
        norm_ids = {
            "phone": sorted({normalize_value("PHONE", p) for p in ids.get("phone", []) if p}),
            "vehicle": sorted({normalize_value("VEHICLE", v) for v in ids.get("vehicle", []) if v}),
            "account": sorted({normalize_value("BANK_ACCOUNT", a) for a in ids.get("account", []) if a}),
            "location": sorted({normalize_value("LOCATION", l) for l in ids.get("location", []) if l}),
        }
        db.add(Entity(
            entity_type="PERSON",
            original_value=name,
            normalized_value=nv,
            confidence=0.95,
            extraction_method="mention",
            source_document_id=document.id,
            source_reference=m.get("source_ref") or document.filename,
            case_id=case_id,
            observed_date=m.get("date"),
            observed_time=m.get("time"),
            meta={"identifiers": norm_ids},
        ))
    # events
    for e in bundle.get("events", []):
        db.add(Event(
            case_id=case_id,
            event_type=e.get("type"),
            description=e.get("description"),
            observed_date=e.get("date"),
            observed_time=e.get("time"),
            date_precision=e.get("precision", "date_only"),
            source_document_id=document.id,
            source_reference=e.get("source_ref"),
            meta={"a_name": e.get("a_name"), "b_name": e.get("b_name"),
                  **e.get("metadata", {})},
        ))
    db.commit()


def _set_stage(db, document, job, stage):
    document.status = stage
    job.stage = stage
    db.commit()


def _counts(db, case_id):
    entities = db.query(Entity).filter(Entity.case_id == case_id).count()
    events = db.query(Event).filter(Event.case_id == case_id).count()
    persons = db.query(Person).count()
    evidence = db.query(Evidence).filter(Evidence.case_id == case_id).count()
    return {"entities": entities, "events": events, "persons": persons,
            "evidence": evidence}


def _evidence_linked_relationships(db, document):
    """Count relationship pairs supported by this document's evidence."""
    pairs = set()
    rows = (db.query(Evidence)
            .filter(Evidence.source_document_id == document.id)
            .filter(Evidence.person_a_id.isnot(None),
                    Evidence.person_b_id.isnot(None))
            .all())
    for e in rows:
        pairs.add(tuple(sorted([e.person_a_id, e.person_b_id])))
    return len(pairs)


def _audit(db, document, action, details=None):
    db.add(AuditLog(
        user_id=document.uploaded_by,
        action=action,
        entity_type="document",
        entity_id=document.id,
        details={"filename": document.filename, **(details or {})},
    ))


def process_document(db: Session, document: Document, content: bytes,
                     mapping: dict = None):
    """Run the full pipeline for one document.

    Advances through the PRD stages (validating -> parsing|ocr_processing ->
    extracting -> normalizing -> resolving -> analyzing -> completed|failed)
    and records per-import statistics + audit events. ``mapping`` optionally
    carries the CSV canonical-field mapping chosen by the investigator.
    """
    job = ProcessingJob(document_id=document.id, status="processing", stage="validating")
    db.add(job)
    db.commit()
    try:
        before = _counts(db, document.case_id)

        _set_stage(db, document, job, "validating")
        ftype = detect_type(document.filename, content)
        document.file_type = ftype
        validation = validate_file(document.filename, content)
        if not validation["ok"]:
            message = validation["errors"][0]
            document.status = "failed"
            document.error = message
            job.status = "failed"
            job.message = message
            db.commit()
            _audit(db, document, "dataset_failed",
                   {"stage": "validating", "error": message})
            db.commit()
            return
        document.warnings = validation.get("warnings", []) or []
        mapping = mapping or validation.get("mapping")

        # -------- parse / OCR
        needs_ocr = False
        text = ""
        if ftype == PDF:
            _set_stage(db, document, job, "parsing")
            text = _extract_pdf_text(content)
            if not text.strip():
                _set_stage(db, document, job, "ocr_processing")
                text, needs_ocr = _ocr_text(content)
                if not text.strip():
                    document.status = "failed"
                    document.error = ("PDF contains no readable text and OCR failed "
                                      "(Tesseract unavailable?).")
                    job.status = "failed"
                    job.message = document.error
                    db.commit()
                    _audit(db, document, "dataset_failed",
                           {"stage": "ocr_processing", "error": document.error})
                    db.commit()
                    return
        elif ftype == CSV:
            _set_stage(db, document, job, "parsing")
            text = content.decode("utf-8", "ignore")
        elif ftype == JSON:
            _set_stage(db, document, job, "parsing")
            text = content.decode("utf-8", "ignore")
        else:
            _set_stage(db, document, job, "parsing")
            try:
                text = content.decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                text = content.decode("latin-1", "ignore")
        document.source_text = text

        # -------- extract
        _set_stage(db, document, job, "extracting")
        bundle_warnings = []
        if ftype == CSV:
            rows = list(csv.reader(io.StringIO(text)))
            bundle = extract_csv_rows(rows, document.filename, document.id,
                                      document.case_id, mapping=mapping)
            bundle_warnings = bundle.get("warnings", [])
            document.mapping = {k: v for k, v in (mapping or {}).items()}
        elif ftype == JSON:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                message = f"JSON structure is invalid ({exc.msg})."
                document.status = "failed"
                document.error = message
                job.status = "failed"
                job.message = message
                db.commit()
                _audit(db, document, "dataset_failed",
                       {"stage": "extracting", "error": message})
                db.commit()
                return
            if isinstance(data, dict):
                data = [data]
            bundle = extract_json_records(data, document.filename, document.id,
                                          document.case_id)
        else:
            bundle = extract_text(text, document.id, document.filename,
                                  document.case_id)

        if bundle_warnings:
            warnings = list(validation.get("warnings", []) or [])
            for w in bundle_warnings:
                if w not in warnings:
                    warnings.append(w)
            document.warnings = warnings
            db.commit()

        # -------- normalize + persist
        _set_stage(db, document, job, "normalizing")
        _persist_entities(db, bundle, document, document.case_id)

        # -------- resolve (same-person clustering + profiles)
        _set_stage(db, document, job, "resolving")
        recompute_case(db, document.case_id)

        # -------- analyze (relationships + evidence strength)
        _set_stage(db, document, job, "analyzing")
        # relationships/evidence are produced inside recompute_case above

        # -------- statistics + completion
        after = _counts(db, document.case_id)
        document.records_processed = max(0, after["events"] - before["events"])
        document.entities_discovered = max(0, after["entities"] - before["entities"])
        document.persons_discovered = max(0, after["persons"] - before["persons"])
        document.evidence_discovered = max(0, after["evidence"] - before["evidence"])
        document.relationships_discovered = _evidence_linked_relationships(db, document)
        document.status = "completed"
        document.processed_at = datetime.utcnow()
        job.status = "completed"
        job.stage = "completed"
        db.commit()
        _audit(db, document, "dataset_completed", {
            "records": document.records_processed,
            "entities": document.entities_discovered,
            "persons": document.persons_discovered,
            "evidence": document.evidence_discovered,
            "relationships": document.relationships_discovered,
            "ocr": needs_ocr,
        })
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Pipeline failed for document %s", document.id)
        db.refresh(document)
        document.status = "failed"
        document.error = _friendly_exception(exc)
        # the detailed technical reason stays in the server logs (logged above);
        # the job/database only receives the investigator-readable message
        if "job" in locals() and job is not None:
            job.status = "failed"
            job.message = document.error
        db.commit()
        try:
            _audit(db, document, "dataset_failed",
                   {"stage": "processing", "error": document.error})
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()


def _friendly_exception(exc):
    """Map an internal exception to an investigator-readable message.

    The full traceback is kept in server logs and in the job's message.
    """
    text = str(exc) or exc.__class__.__name__
    if isinstance(exc, (UnicodeDecodeError,)):
        return "File could not be read as text (encoding error)."
    if "pypdf" in text or "PdfReader" in text:
        return "PDF could not be parsed (corrupt or unsupported PDF)."
    return f"Processing failed: {text[:300]}"


UPLOAD_DIR = DATA_DIR / "uploads"


def save_upload(document_id: str, content: bytes) -> str:
    """Persist raw upload bytes to disk so background processing can read them.

    Files live in a private, id-named directory (never user-supplied paths),
    isolated from the rest of the application.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{document_id}.bin"
    path.write_bytes(content)
    return str(path)


def remove_document_artifacts(db: Session, document: Document):
    """Delete the entities/events this document created so it can be reprocessed.

    Persons/relationships/evidence are rebuilt case-wide by recompute_case()
    after reprocessing, so we only remove the rows this document owns.
    """
    db.query(Event).filter(Event.source_document_id == document.id).delete()
    db.query(Entity).filter(Entity.source_document_id == document.id).delete()
    db.commit()


def run_background(document_id: str):
    """Process an uploaded document in its own session (called from BackgroundTasks)."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if not document:
            return
        path = UPLOAD_DIR / f"{document_id}.bin"
        if not path.exists():
            document.status = "failed"
            document.error = "Uploaded file missing from storage"
            db.commit()
            return
        content = path.read_bytes()
        process_document(db, document, content, mapping=document.mapping or None)
        # The raw upload is only removed after the pipeline *completed*, so a
        # failed document can be retried later without re-uploading the file.
        if db.get(Document, document_id) and document.status == "completed":
            try:
                path.unlink()
            except OSError:
                pass
    finally:
        db.close()


def recompute_case(db: Session, case_id: str):
    """Rebuild persons, profiles, relationships and evidence for a case."""
    # ---- collect person mentions
    mention_rows = db.query(Entity).filter_by(entity_type="PERSON", case_id=case_id).all()
    mentions = [
        {"name": m.original_value, "identifiers": (m.meta or {}).get("identifiers", {})}
        for m in mention_rows
    ]

    # ---- resolve into persons
    clusters = resolve_mentions(mentions)

    # ---- upsert persons (keyed by canonical normalized name) + alias map
    persons = []
    alias_map = {}  # normalized mention name -> person id
    existing = {p.id: p for p in db.query(Person).all()}
    seen_ids = set()
    for c in clusters:
        nv = normalize_name(c["name"])
        pid = "P-" + nv.replace(" ", "_")[:60]
        person = existing.get(pid)
        if not person:
            person = Person(id=pid, name=c["name"])
            db.add(person)
            existing[pid] = person
        person.name = c["name"]
        person.resolution = {
            "variants": sorted({m.get("name") for m in c["mentions"]}),
            "signals": c["signals"],
            "confidence": c["confidence"],
            "merged": len(c["mentions"]) > 1,
        }
        seen_ids.add(pid)
        persons.append({
            "id": pid,
            "name": c["name"],
            "identifiers": c["identifiers"],
            "confidence": c["confidence"],
            "signals": c["signals"],
        })
        # register every mention variant so name->id mapping is robust
        alias_map[nv] = pid
        for m in c["mentions"]:
            alias_map[normalize_name(m.get("name", ""))] = pid
        # record identity-resolution events (system-level) when variants merged.
        # dedupe: keep one audit row per person, updated to the final state.
        if len(c["mentions"]) > 1:
            details = {"name": c["name"],
                       "variants": sorted({m.get("name") for m in c["mentions"]}),
                       "signals": c["signals"], "confidence": c["confidence"]}
            audit_row = (db.query(AuditLog)
                         .filter_by(action="identity_resolution", entity_type="person", entity_id=pid)
                         .first())
            if audit_row:
                audit_row.details = details
            else:
                db.add(AuditLog(user_id=None, action="identity_resolution",
                                entity_type="person", entity_id=pid, details=details))
    db.commit()

    # ---- clear + rebuild person<->entity links for this case
    # (re-link identifier entities by normalized value)
    entities = db.query(Entity).filter(Entity.case_id == case_id).all()
    entities_by_type = {}
    for e in entities:
        entities_by_type.setdefault(e.entity_type, {}).setdefault(e.normalized_value, e)

    # link via person_entities association
    from ..models import person_entities
    # remove existing links for these persons
    for pid in seen_ids:
        db.execute(person_entities.delete().where(person_entities.c.person_id == pid))
    db.commit()

    for p in persons:
        ids = p["identifiers"]
        for (etype, key) in [("phone", "PHONE"), ("vehicle", "VEHICLE"),
                             ("account", "BANK_ACCOUNT"), ("location", "LOCATION")]:
            for val in ids.get(etype, []):
                ent = entities_by_type.get(key, {}).get(val)
                if ent:
                    db.execute(person_entities.insert().values(
                        person_id=p["id"], entity_id=ent.id, role=etype))
    db.commit()

    # ---- attach case membership to persons
    person_case_ids = {p["id"]: [] for p in persons}
    for p in persons:
        person_case_ids[p["id"]].append(case_id)

    # ---- map event names -> canonical person ids via the alias map
    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_dicts = []
    for ev in events:
        a_name = (ev.meta or {}).get("a_name")
        b_name = (ev.meta or {}).get("b_name")
        pa = alias_map.get(normalize_name(a_name)) if a_name else None
        pb = alias_map.get(normalize_name(b_name)) if b_name else None
        ev.person_a_id = pa
        ev.person_b_id = pb
        event_dicts.append({
            "id": ev.id,
            "type": ev.event_type,
            "description": ev.description,
            "date": ev.observed_date,
            "time": ev.observed_time,
            "precision": ev.date_precision,
            "a_name": a_name,
            "b_name": b_name,
            "person_a_id": pa,
            "person_b_id": pb,
            "source_ref": ev.source_reference,
            "source_document_id": ev.source_document_id,
            "metadata": ev.meta or {},
            "case_id": case_id,
        })
    db.commit()

    # ---- build entities dicts for relationship engine
    entity_dicts = [
        {"type": e.entity_type, "value": e.original_value,
         "normalized_value": e.normalized_value, "source": e.source_reference}
        for e in entities
    ]

    # attach case membership into person dicts
    for p in persons:
        p["cases"] = person_case_ids[p["id"]]

    # ---- discover relationships
    rels = discover_relationships(persons, event_dicts, entity_dicts)

    # ---- persist relationships
    existing_rels = {r.id: r for r in db.query(Relationship).filter(
        Relationship.person_a_id.in_(seen_ids)).all()}
    for r in rels:
        rel = existing_rels.get(r["id"])
        if not rel:
            rel = Relationship(id=r["id"], person_a_id=r["person_a"], person_b_id=r["person_b"])
            db.add(rel)
            existing_rels[r["id"]] = rel
        rel.score = r["score"]
        rel.strength = r["strength"]
        rel.signals = r["signals"]
    db.commit()

    # ---- persist evidence
    _rebuild_evidence(db, case_id, persons, event_dicts, seen_ids)


def _rebuild_evidence(db, case_id, persons, events, seen_ids):
    # delete case evidence tied to these persons (recompute-all for simplicity)
    db.query(Evidence).filter(Evidence.case_id == case_id).delete()
    db.commit()

    counter = 0
    for ev in events:
        pa, pb = ev.get("person_a_id"), ev.get("person_b_id")
        if not pa or not pb or pa == pb:
            continue
        etype = (ev.get("type") or "").upper()
        if etype == "CALL":
            kind = "call_association"
            confidence = 0.94
        elif etype == "TRANSACTION":
            kind = "transaction_association"
            confidence = 0.92
        elif etype == "LOCATION_OBSERVATION":
            kind = "location_association"
            confidence = 0.88
        else:
            kind = "event_association"
            confidence = 0.7
        counter += 1
        db.add(Evidence(
            id=f"E{counter}-{case_id}",
            type=kind,
            person_a_id=pa,
            person_b_id=pb,
            source_document_id=ev.get("source_document_id"),
            source_reference=ev.get("source_ref"),
            observed_date=ev.get("date"),
            observed_time=ev.get("time"),
            date_precision=ev.get("precision", "date_only"),
            confidence=confidence,
            case_id=case_id,
            details={"description": ev.get("description"), **ev.get("metadata", {})},
        ))
    db.commit()
