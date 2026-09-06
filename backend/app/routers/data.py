import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case, Document, ProcessingJob, User
from ..security import get_current_user, ensure_case_access, log_audit
from ..services.pipeline import process_document

router = APIRouter(tags=["cases", "documents"])


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
            {"id": d.id, "filename": d.filename, "file_type": d.file_type, "status": d.status}
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
    return c_to_dict(case)


# ---------------------------------------------------------------- uploads
@router.post("/cases/{case_id}/upload")
def upload(case_id: str, file: UploadFile = File(...),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_case_access(db, user, case_id)
    content = file.file.read()
    fname = file.filename or "upload.bin"
    allowed = (".pdf", ".csv", ".json", ".txt", ".text")
    if not any(fname.lower().endswith(e) for e in allowed):
        raise HTTPException(400, "Unsupported file type")
    doc = Document(id="DOC-" + uuid.uuid4().hex[:8].upper(), case_id=case_id,
                   filename=fname, uploaded_by=user.id)
    db.add(doc)
    db.commit()
    log_audit(db, user.id, "upload", "document", doc.id, {"filename": fname})
    process_document(db, doc, content)
    db.refresh(doc)
    return {"id": doc.id, "filename": doc.filename, "status": doc.status, "error": doc.error}


# ---------------------------------------------------------------- processing
@router.get("/documents/{doc_id}/status")
def doc_status(doc_id: str, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    ensure_case_access(db, user, doc.case_id)
    jobs = db.query(ProcessingJob).filter_by(document_id=doc_id).order_by(ProcessingJob.id.desc()).all()
    return {
        "id": doc.id, "filename": doc.filename, "status": doc.status, "error": doc.error,
        "file_type": doc.file_type,
        "jobs": [{"status": j.status, "stage": j.stage, "message": j.message} for j in jobs],
    }


@router.get("/processing")
def processing_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.query(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(50).all()
    return [
        {"id": j.id, "document_id": j.document_id, "status": j.status,
         "stage": j.stage, "message": j.message}
        for j in jobs
    ]
