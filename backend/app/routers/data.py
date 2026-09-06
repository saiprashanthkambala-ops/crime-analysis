import json
import uuid

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case, Document, ProcessingJob, User
from ..security import get_current_user, ensure_case_access, log_audit
from ..services.dataset_import import (MAX_BYTES, detect_extension, file_sha256,
                                       friendly_size, normalize_filename,
                                       validate_file)
from ..services.pipeline import (process_document, remove_document_artifacts,
                                 run_background, save_upload)

router = APIRouter(prefix="/api", tags=["cases", "documents", "imports"])


# ---------------------------------------------------------------- cases
@router.get("/cases")
def list_cases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        cases = db.query(Case).all()
    else:
        cases = user.assigned_cases
    return [c_to_dict(c) for c in cases]


def c_to_dict(c: Case):
    return {
        "id": c.id, "name": c.name, "description": c.description,
        "status": c.status, "created_at": c.created_at.isoformat() if c.created_at else None,
        "documents": [
            {
                "id": d.id, "filename": d.filename, "file_type": d.file_type,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in c.documents
        ],
    }


class CaseCreate(BaseModel):
    name: str
    description: str = ""
    id: str = None


@router.post("/cases")
def create_case(body: CaseCreate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    cid = body.id or ("C-" + uuid.uuid4().hex[:6].upper())
    case = Case(id=cid, name=body.name, description=body.description, created_by=user.id)
    db.add(case)
    db.commit()
    case.users.append(user)
    db.commit()
    log_audit(db, user.id, "create_case", "case", cid)
    return c_to_dict(case)


@router.get("/cases/{case_id}")
def get_case(case_id: str, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    ensure_case_access(db, user, case_id)
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    log_audit(db, user.id, "case_access", "case", case_id)
    return c_to_dict(case)


# ================================================================ dataset import
# Shared helpers --------------------------------------------------------------

def _doc_summary(db: Session, doc: Document):
    """Serialization of one import record (history / status payload)."""
    users = {u.id: u.username for u in db.query(User).all()} if doc.uploaded_by else {}
    return {
        "id": doc.id, "filename": doc.filename, "file_type": doc.file_type,
        "status": doc.status, "error": doc.error,
        "uploaded_by": doc.uploaded_by,
        "uploaded_by_name": users.get(doc.uploaded_by),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
        "file_size": doc.file_size or 0,
        "sha256": doc.sha256,
        "records_processed": doc.records_processed or 0,
        "entities_discovered": doc.entities_discovered or 0,
        "persons_discovered": doc.persons_discovered or 0,
        "relationships_discovered": doc.relationships_discovered or 0,
        "evidence_discovered": doc.evidence_discovered or 0,
        "warnings": doc.warnings or [],
        "mapping": doc.mapping or {},
        "detected_columns": doc.detected_columns or [],
        "retry_count": doc.retry_count or 0,
        "case_id": doc.case_id,
    }


def _parse_mapping_param(raw):
    """Parse the optional CSV ``mapping`` form field.

    Accepted formats:
      * an array aligned with the uploaded files: [{field: column}, ...]
      * an object (single-file convenience):      {field: column}
    """
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Column mapping is not valid JSON.")
    return parsed


def _existing_duplicate(db, case_id, sha):
    if not sha:
        return None
    return (db.query(Document)
            .filter(Document.case_id == case_id, Document.sha256 == sha)
            .first())


def _store_document(db, user, case_id, filename, content, file_type,
                    mapping=None, detected_columns=None, status="queued"):
    doc = Document(
        id="DOC-" + uuid.uuid4().hex[:8].upper(),
        case_id=case_id,
        filename=filename,
        file_type=file_type,
        status=status,
        uploaded_by=user.id,
        file_size=len(content),
        sha256=file_sha256(content),
        mapping=mapping or {},
        detected_columns=detected_columns or [],
    )
    db.add(doc)
    db.commit()
    job = ProcessingJob(document_id=doc.id, status="queued", stage="queued")
    db.add(job)
    db.commit()
    save_upload(doc.id, content)
    return doc


def _append_import_errors(collection, filename, error, extra=None):
    item = {"filename": filename, "error": error}
    if extra:
        item.update(extra)
    collection.append(item)


def _import_http_code(errors):
    """409 when every problem is a duplicate; 400 for genuine validation errors."""
    if errors and all(e.get("document_id") for e in errors):
        return 409
    return 400


# ------------------------------------------------- legacy single-file upload
@router.post("/cases/{case_id}/upload")
def upload(case_id: str, background: BackgroundTasks, file: UploadFile = File(...),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Legacy single-file upload (kept for API compatibility).

    Performs synchronous safety checks (type/size/emptiness); deeper content
    validation happens inside the async pipeline, which records a clean
    "failed" state for invalid payloads.
    """
    ensure_case_access(db, user, case_id)
    content = file.file.read()
    fname = normalize_filename(file.filename or "upload.bin")
    ext = detect_extension(fname)
    allowed = (".pdf", ".csv", ".json", ".txt", ".text")
    if ext is None or not any(fname.lower().endswith(e) for e in allowed):
        raise HTTPException(400, "Unsupported file type. Supported formats: PDF, CSV, JSON, TXT.")
    if len(content) > MAX_BYTES():
        raise HTTPException(400, f"File exceeds the maximum allowed size "
                                 f"({friendly_size(MAX_BYTES())}).")
    if not content.strip():
        raise HTTPException(400, "File is empty.")
    sha = file_sha256(content)
    dup = _existing_duplicate(db, case_id, sha)
    if dup:
        raise HTTPException(
            409, f"Duplicate import blocked: '{dup.filename}' was already imported "
                 f"into this case (identical content, {dup.id}). Use the history "
                 f"view to retry it instead of uploading again.")
    doc = _store_document(db, user, case_id, fname, content, None, status="uploaded")
    log_audit(db, user.id, "dataset_upload", "document", doc.id,
              {"filename": fname, "file_type": doc.file_type, "size": len(content),
               "sha256": sha, "endpoint": "legacy"})
    background.add_task(run_background, doc.id)
    return {"id": doc.id, "filename": doc.filename, "status": doc.status,
            "error": doc.error, "file_type": doc.file_type, "sha256": sha}


# ------------------------------------------------- import preflight validation
@router.post("/cases/{case_id}/imports/preflight")
def preflight_import(case_id: str, files: list[UploadFile] = File(...),
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Validate files *before* they are imported.

    Returns per-file validation results (type sniffing, size/emptiness checks,
    CSV/JSON structure, detected columns + suggested mapping, duplicate
    detection). Nothing is persisted by this endpoint.
    """
    ensure_case_access(db, user, case_id)
    if not files:
        raise HTTPException(400, "No files were provided.")
    results = []
    seen_shas = {}
    for f in files:
        content = f.file.read()
        fname = normalize_filename(f.filename or "upload.bin")
        result = validate_file(fname, content)
        result["declared_filename"] = f.filename
        result["size"] = len(content)
        # duplicate check — against already-imported documents and within the batch
        sha = file_sha256(content)
        if result["ok"]:
            dup = _existing_duplicate(db, case_id, sha)
            if not dup and sha in seen_shas:
                result["ok"] = False
                result["errors"].append(
                    f"Duplicate import: two selected files have identical content "
                    f"('{seen_shas[sha]}'). Remove the duplicate before importing.")
            elif dup:
                result["ok"] = False
                result["errors"].append(
                    f"Duplicate import: identical content was already imported as "
                    f"'{dup.filename}' ({dup.id}). Use the history view to retry it.")
                result["duplicate"] = {"document_id": dup.id, "filename": dup.filename,
                                       "status": dup.status}
        if result["ok"]:
            seen_shas[sha] = fname
        results.append(result)
    return {"files": results}


# ------------------------------------------------- dataset import (multi-file)
@router.post("/cases/{case_id}/imports")
def import_datasets(case_id: str, background: BackgroundTasks,
                    files: list[UploadFile] = File(...),
                    mapping: str = Form(None),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Import one or more validated datasets into a case.

    The whole batch is validated first; if any file is invalid the request is
    rejected and *nothing* is imported (no silent partial ingestion). Accepted
    files are queued for the standard background pipeline immediately.
    """
    ensure_case_access(db, user, case_id)
    if not files:
        raise HTTPException(400, "No files were provided.")
    raw_mappings = _parse_mapping_param(mapping)
    if raw_mappings is None:
        per_file_mappings = [None] * len(files)
    elif isinstance(raw_mappings, list):
        if len(raw_mappings) != len(files):
            raise HTTPException(400, "Column mapping array must have one entry per "
                                     "uploaded file.")
        per_file_mappings = raw_mappings
    elif isinstance(raw_mappings, dict) and len(files) == 1:
        per_file_mappings = [raw_mappings]
    else:
        raise HTTPException(400, "Column mapping must be an array with one entry per "
                                 "uploaded file (or a single object for one file).")

    # ---- phase 1: validate the whole batch, import nothing on any failure
    errors = []
    validated = []
    batch_seen_shas = {}
    for i, f in enumerate(files):
        content = f.file.read()
        fname = normalize_filename(f.filename or "upload.bin")
        result = validate_file(fname, content)
        if not result["ok"]:
            for err in result["errors"]:
                _append_import_errors(errors, fname, err)
            continue
        sha = file_sha256(content)
        dup = _existing_duplicate(db, case_id, sha)
        if not dup and sha in batch_seen_shas:
            _append_import_errors(
                errors, fname,
                f"Duplicate import: identical content was already selected as "
                f"'{batch_seen_shas[sha]}' in this batch.")
            continue
        if dup:
            _append_import_errors(errors, fname,
                                  f"Duplicate import: identical content was already "
                                  f"imported as '{dup.filename}' ({dup.id}).",
                                  {"document_id": dup.id})
            continue
        batch_seen_shas[sha] = fname
        mapping_i = per_file_mappings[i]
        if mapping_i and result["file_type"] != "csv":
            _append_import_errors(errors, fname,
                                  "Column mapping only applies to CSV files.")
            continue
        if result["file_type"] == "csv" and mapping_i:
            from ..services.dataset_import import validate_mapping_columns
            cleaned, map_errors = validate_mapping_columns(mapping_i, result["columns"])
            if map_errors:
                for me in map_errors:
                    _append_import_errors(errors, fname, me)
                continue
            mapping_i = cleaned
        validated.append((fname, content, result, mapping_i))

    if errors:
        # nothing was persisted
        log_audit(db, user.id, "dataset_validate", "case", case_id,
                  {"result": "rejected", "errors": errors})
        first = errors[0]["error"]
        raise HTTPException(_import_http_code(errors),
                            detail={"message": "Import rejected — see file errors.",
                                    "errors": errors, "example": first})
    log_audit(db, user.id, "dataset_validate", "case", case_id,
              {"result": "ok", "files": [v[0] for v in validated]})

    # ---- phase 2: persist + queue every validated file
    imported = []
    for fname, content, result, mapping_i in validated:
        doc = _store_document(
            db, user, case_id, fname, content, result["file_type"],
            mapping=mapping_i, detected_columns=result.get("columns"),
        )
        log_audit(db, user.id, "dataset_upload", "document", doc.id,
                  {"filename": fname, "file_type": result["file_type"],
                   "size": len(content), "sha256": doc.sha256,
                   "mapping": mapping_i or {}})
        imported.append({
            "id": doc.id, "filename": doc.filename, "file_type": doc.file_type,
            "status": doc.status, "records": result.get("rows"),
            "needs_ocr": result.get("needs_ocr", False),
        })
        background.add_task(run_background, doc.id)
    return {"imports": imported, "count": len(imported)}


# ------------------------------------------------- import history
@router.get("/cases/{case_id}/imports")
def import_history(case_id: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    ensure_case_access(db, user, case_id)
    docs = (db.query(Document)
            .filter(Document.case_id == case_id)
            .order_by(Document.created_at.desc())
            .all())
    return {"imports": [_doc_summary(db, d) for d in docs]}


# ------------------------------------------------- retry a failed import
@router.post("/documents/{doc_id}/retry")
def retry_import(doc_id: str, background: BackgroundTasks,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    ensure_case_access(db, user, doc.case_id)
    if doc.status not in ("failed",):
        raise HTTPException(400, "Only failed imports can be retried.")
    # remove artifacts created by the previous attempt so nothing is duplicated
    remove_document_artifacts(db, doc)
    doc.status = "queued"
    doc.error = None
    doc.retry_count = (doc.retry_count or 0) + 1
    db.commit()
    job = ProcessingJob(document_id=doc.id, status="queued", stage="queued")
    db.add(job)
    db.commit()
    log_audit(db, user.id, "dataset_retry", "document", doc.id,
              {"filename": doc.filename, "attempt": doc.retry_count})
    background.add_task(run_background, doc.id)
    return {"id": doc.id, "filename": doc.filename, "status": doc.status,
            "retry_count": doc.retry_count}


# ---------------------------------------------------------------- processing
@router.get("/documents/{doc_id}/status")
def doc_status(doc_id: str, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    ensure_case_access(db, user, doc.case_id)
    jobs = db.query(ProcessingJob).filter_by(document_id=doc_id).order_by(ProcessingJob.id.desc()).all()
    summary = _doc_summary(db, doc)
    summary["jobs"] = [
        {
            "id": j.id, "status": j.status, "stage": j.stage,
            "message": j.message,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs
    ]
    return summary


@router.get("/processing")
def processing_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.query(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(50).all()
    return [
        {"id": j.id, "document_id": j.document_id, "status": j.status,
         "stage": j.stage, "message": j.message}
        for j in jobs
    ]
