from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case, Document, Entity, Event, Evidence, Person, Relationship, User, person_entities
from ..security import get_current_user, log_audit
from ..services.profile import build_profile
from ..services.timeline import build_timeline
from ..services.graph import build_graph

router = APIRouter(tags=["intelligence"])


def _person_from_id(db, pid):
    return db.get(Person, pid)


# ---------------------------------------------------------------- search
@router.get("/search")
def search(q: str = Query(...), user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    query = q.strip()
    if not query:
        return {"people": [], "entities": [], "cases": []}
    nq = query.lower()

    people = db.query(Person).filter(Person.name.ilike(f"%{query}%")).all()
    entities = (
        db.query(Entity)
        .filter(or_(Entity.original_value.ilike(f"%{query}%"),
                    Entity.normalized_value.ilike(f"%{nq}%")))
        .limit(50)
        .all()
    )
    cases = db.query(Case).filter(or_(Case.name.ilike(f"%{query}%"),
                                      Case.id.ilike(f"%{query}%"))).all()

    log_audit(db, user.id, "search", details={"query": query})
    return {
        "people": [
            {"person_id": p.id, "name": p.name} for p in people
        ],
        "entities": [
            {"id": e.id, "type": e.entity_type, "value": e.original_value,
             "normalized": e.normalized_value, "case_id": e.case_id}
            for e in entities
        ],
        "cases": [{"id": c.id, "name": c.name, "status": c.status} for c in cases],
    }


# ---------------------------------------------------------------- persons
@router.get("/persons")
def list_persons(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    persons = db.query(Person).all()
    return [
        {"person_id": p.id, "name": p.name} for p in persons
    ]


@router.get("/persons/{person_id}")
def get_person(person_id: str, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    profile = build_profile(db, person_id)
    if not profile:
        raise HTTPException(404, "Person not found")
    log_audit(db, user.id, "view_profile", "person", person_id)
    return profile


# ---------------------------------------------------------------- relationships
def _rel_dict(db, r):
    pa = _person_from_id(db, r.person_a_id)
    pb = _person_from_id(db, r.person_b_id)
    evidence = (
        db.query(Evidence)
        .filter(or_(
            (Evidence.person_a_id == r.person_a_id) & (Evidence.person_b_id == r.person_b_id),
            (Evidence.person_a_id == r.person_b_id) & (Evidence.person_b_id == r.person_a_id),
        ))
        .all()
    )
    return {
        "id": r.id,
        "person_a": {"id": r.person_a_id, "name": pa.name if pa else r.person_a_id},
        "person_b": {"id": r.person_b_id, "name": pb.name if pb else r.person_b_id},
        "score": r.score,
        "strength": r.strength,
        "signals": r.signals,
        "decision": r.decision,
        "evidence": [
            {
                "id": e.id, "type": e.type, "source": e.source_reference,
                "date": e.observed_date, "time": e.observed_time,
                "confidence": e.confidence, "details": e.details,
            }
            for e in evidence
        ],
        "dates": sorted({e.observed_date for e in evidence if e.observed_date}),
        "sources": sorted({e.source_reference for e in evidence if e.source_reference}),
    }


@router.get("/relationships")
def list_relationships(strength: str = None, case_id: str = None,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Relationship)
    if strength:
        q = q.filter(Relationship.strength == strength.upper())
    rels = q.all()
    return [_rel_dict(db, r) for r in rels]


@router.get("/relationships/{rel_id}")
def get_relationship(rel_id: str, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    r = db.get(Relationship, rel_id)
    if not r:
        raise HTTPException(404, "Relationship not found")
    log_audit(db, user.id, "view_relationship", "relationship", rel_id)
    return _rel_dict(db, r)


# ---------------------------------------------------------------- evidence
@router.get("/evidence")
def list_evidence(case_id: str = None, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    q = db.query(Evidence)
    if case_id:
        q = q.filter(Evidence.case_id == case_id)
    evs = q.all()
    return [
        {
            "id": e.id, "type": e.type,
            "person_a": e.person_a_id, "person_b": e.person_b_id,
            "source": e.source_reference, "date": e.observed_date,
            "time": e.observed_time, "confidence": e.confidence,
            "details": e.details,
        }
        for e in evs
    ]


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    e = db.get(Evidence, evidence_id)
    if not e:
        raise HTTPException(404, "Evidence not found")
    log_audit(db, user.id, "view_evidence", "evidence", evidence_id)
    return {
        "id": e.id, "type": e.type, "person_a": e.person_a_id, "person_b": e.person_b_id,
        "source": e.source_reference, "date": e.observed_date, "time": e.observed_time,
        "confidence": e.confidence, "details": e.details, "case_id": e.case_id,
    }


# ---------------------------------------------------------------- timeline
@router.get("/timeline")
def timeline(case_id: str = None, person_id: str = None, event_type: str = None,
             start: str = None, end: str = None,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    events = db.query(Event).all()
    items = build_timeline(
        [{
            "id": e.id, "type": e.event_type, "description": e.description,
            "date": e.observed_date, "time": e.observed_time,
            "precision": e.date_precision, "case_id": e.case_id,
            "person_a_id": e.person_a_id, "person_b_id": e.person_b_id,
            "source": e.source_reference, "metadata": e.meta,
        } for e in events],
        case_id=case_id, person_id=person_id, event_type=event_type, start=start, end=end,
    )
    return items


# ---------------------------------------------------------------- graph
@router.get("/graph")
def graph(case_id: str = None, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    persons = db.query(Person).all()
    events = db.query(Event).all()
    entities = db.query(Entity).all()
    rels = db.query(Relationship).all()

    person_dicts = []
    for p in persons:
        profile = build_profile(db, p.id)
        person_dicts.append({
            "id": p.id, "name": p.name,
            "identifiers": profile["identifiers"],
            "cases": profile["cases"],
        })
    event_dicts = [
        {
            "id": e.id, "type": e.event_type, "description": e.description,
            "date": e.observed_date, "time": e.observed_time,
            "a_name": (e.meta or {}).get("a_name"),
            "b_name": (e.meta or {}).get("b_name"),
            "case_id": e.case_id,
        }
        for e in events
    ]
    entity_dicts = [
        {"type": e.entity_type, "value": e.original_value,
         "normalized_value": e.normalized_value}
        for e in entities
    ]
    rel_dicts = [
        {"id": r.id, "person_a": r.person_a_id, "person_b": r.person_b_id,
         "strength": r.strength, "score": r.score}
        for r in rels
    ]
    g = build_graph(person_dicts, event_dicts, entity_dicts, rel_dicts)
    return g


# ---------------------------------------------------------------- feedback
class FeedbackBody(BaseModel):
    decision: str  # relevant | incorrect | needs_review
    note: str = ""


@router.post("/relationships/{rel_id}/feedback")
def feedback(rel_id: str, body: FeedbackBody, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    if body.decision not in ("relevant", "incorrect", "needs_review"):
        raise HTTPException(400, "Invalid decision")
    r = db.get(Relationship, rel_id)
    if not r:
        raise HTTPException(404, "Relationship not found")
    r.decision = body.decision
    r.decided_by = user.id
    r.decided_at = __import__("datetime").datetime.utcnow()
    from ..models import Feedback
    db.add(Feedback(relationship_id=rel_id, user_id=user.id, decision=body.decision,
                    note=body.note))
    db.commit()
    log_audit(db, user.id, "feedback", "relationship", rel_id,
              {"decision": body.decision})
    return {"ok": True, "decision": body.decision}
