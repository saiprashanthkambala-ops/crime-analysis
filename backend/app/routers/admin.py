from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User, Case
from ..security import get_current_user, require_admin, hash_password, log_audit

router = APIRouter(prefix="/api", tags=["admin"])


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
    log_audit(db, user.id, "admin_action", "user", str(u.id),
              {"action": "create_user", "username": body.username, "role": body.role})
    return u.as_dict()


@router.get("/admin/investigators/overview")
def investigator_overview(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Return investigator access/assignment/activity details for the admin console.

    Passwords are intentionally never exposed. The stored password is a one-way
    hash and cannot be used as a login credential by the UI.
    """
    investigators = (
        db.query(User)
        .filter(User.role == "investigator")
        .order_by(User.username.asc())
        .all()
    )
    cases = db.query(Case).all()
    case_by_id = {c.id: c for c in cases}
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.id.desc())
        .limit(1000)
        .all()
    )

    latest_activity = {}
    latest_login = {}
    for log in logs:
        if log.user_id is None:
            continue
        if log.user_id not in latest_activity:
            latest_activity[log.user_id] = log
        if log.action == "login" and log.user_id not in latest_login:
            latest_login[log.user_id] = log

    result = []
    for investigator in investigators:
        assigned = list(investigator.assigned_cases)
        case_activity = []
        seen_case_ids = set()
        for log in logs:
            if log.user_id != investigator.id or log.entity_type != "case" or not log.entity_id:
                continue
            cid = str(log.entity_id)
            if cid in seen_case_ids:
                continue
            case = case_by_id.get(cid)
            case_activity.append({
                "case_id": cid,
                "case_name": case.name if case else cid,
                "action": log.action,
                "at": log.created_at.isoformat() if log.created_at else None,
            })
            seen_case_ids.add(cid)
            if len(case_activity) >= 5:
                break

        result.append({
            "id": investigator.id,
            "username": investigator.username,
            "full_name": investigator.full_name,
            "email": investigator.email,
            "role": investigator.role,
            "is_active": investigator.is_active,
            "created_at": investigator.created_at.isoformat() if investigator.created_at else None,
            "assigned_cases": [
                {
                    "id": case.id,
                    "name": case.name,
                    "status": case.status,
                }
                for case in assigned
            ],
            "last_login": (
                latest_login[investigator.id].created_at.isoformat()
                if investigator.id in latest_login and latest_login[investigator.id].created_at
                else None
            ),
            "last_activity": (
                latest_activity[investigator.id].created_at.isoformat()
                if investigator.id in latest_activity and latest_activity[investigator.id].created_at
                else None
            ),
            "recent_case_activity": case_activity,
        })

    return {
        "investigators": result,
        "note": "Passwords are never displayed or returned by this endpoint. Use the admin user-management controls to create accounts or set credentials.",
    }


@router.get("/admin/cases")
def admin_cases(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    all_users = {u.id: u.username for u in db.query(User).all()}
    return [
        {
            "id": c.id, "name": c.name, "status": c.status,
            "assigned": [u.id for u in c.users],
        }
        for c in cases
    ]


class CaseAssignment(BaseModel):
    user_id: int
    action: str  # add | remove


@router.post("/admin/cases/{case_id}/users")
def assign_case_user(case_id: str, body: CaseAssignment,
                     user: User = Depends(require_admin), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    target = db.get(User, body.user_id)
    if not target:
        raise HTTPException(404, "User not found")
    assigned = [u.id for u in case.users]
    if body.action == "add" and target.id not in assigned:
        case.users.append(target)
    elif body.action == "remove" and target.id in assigned:
        case.users.remove(target)
    else:
        raise HTTPException(400, "Invalid action or state")
    db.commit()
    log_audit(db, user.id, "admin_action", "case", case_id,
              {"action": f"assign_{body.action}", "user_id": body.user_id})
    return {"ok": True, "assigned": [u.id for u in case.users]}


@router.get("/admin/stats")
def stats(user: User = Depends(require_admin), db: Session = Depends(get_db)):
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
