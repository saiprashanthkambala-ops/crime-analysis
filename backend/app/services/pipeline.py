"""End-to-end ingestion + analysis pipeline.

process_document() parses an uploaded file, extracts entities/events, persists
them with provenance, then triggers recompute_case() which (re)builds persons,
profiles, relationships and evidence for the whole case.
"""
import csv
import io
import json
import shutil
import subprocess
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Case, Document, Entity, Event, Evidence, Person, Relationship, ProcessingJob
from ..config import settings
from .extraction import extract_text, extract_csv_rows, extract_json_records
from .normalization import normalize_value, normalize_name
from .resolution import resolve_mentions
from .relationships import discover_relationships

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
    except Exception:
        pass
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
    except Exception:
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
            source_reference=m.get("source_ref"),
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


def process_document(db: Session, document: Document, content: bytes):
    job = ProcessingJob(document_id=document.id, status="processing", stage="parsing")
    db.add(job)
    db.commit()
    try:
        document.status = "processing"
        db.commit()

        text, ftype, needs_ocr = extract_document_content(document.filename, content)
        document.file_type = ftype
        document.source_text = text

        job.stage = "extracting"
        db.commit()

        if ftype == CSV:
            rows = list(csv.reader(io.StringIO(text)))
            bundle = extract_csv_rows(rows, document.filename, document.id, document.case_id)
        elif ftype == JSON:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                document.status = "failed"
                document.error = "Invalid JSON"
                job.status = "failed"
                db.commit()
                return
            if isinstance(data, dict):
                data = [data]
            bundle = extract_json_records(data, document.filename, document.id, document.case_id)
        else:
            bundle = extract_text(text, document.id, document.filename, document.case_id)

        job.stage = "persisting"
        db.commit()
        _persist_entities(db, bundle, document, document.case_id)

        job.stage = "analyzing"
        db.commit()
        recompute_case(db, document.case_id)

        document.status = "completed"
        document.processed_at = datetime.utcnow()
        job.status = "completed"
        job.stage = "completed"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        document.status = "failed"
        document.error = str(exc)
        job.status = "failed"
        job.message = str(exc)
        db.commit()


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
            source_reference=ev.get("source_ref"),
            observed_date=ev.get("date"),
            observed_time=ev.get("time"),
            date_precision=ev.get("precision", "date_only"),
            confidence=confidence,
            case_id=case_id,
            details={"description": ev.get("description"), **ev.get("metadata", {})},
        ))
    db.commit()
