from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User, Case
from ..security import get_current_user, require_admin, hash_password, log_audit

router = APIRouter(tags=["admin"])


@router.get("/audit")
def audit_logs(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(500).all()
    users = {u.id: u.username for u in db.query(User).all()}
    return [
        {
            "id": r.id, "user": users.get(r.user_id, "system"), "action": r.action,
            "entity_type": r.entity_type, "entity_id": r.entity_id,
            "details": r.details, "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/admin/users")
def list_users(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [u.as_dict() for u in db.query(User).all()]


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    role: str = "investigator"


@router.post("/admin/users")
def create_user(body: UserCreate, user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(400, "Username exists")
    u = User(username=body.username, password_hash=hash_password(body.password),
             full_name=body.full_name, email=body.email, role=body.role)
    db.add(u)
    db.commit()
    log_audit(db, user.id, "create_user", "user", str(u.id), {"username": body.username})
    return u.as_dict()


@router.get("/admin/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..models import Document, Entity, Event, Evidence, Person, Relationship
    return {
        "cases": db.query(Case).count(),
        "persons": db.query(Person).count(),
        "relationships": db.query(Relationship).count(),
        "evidence": db.query(Evidence).count(),
        "documents": db.query(Document).count(),
        "entities": db.query(Entity).count(),
        "events": db.query(Event).count(),
    }
