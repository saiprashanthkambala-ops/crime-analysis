"""Dynamic profile assembly.

Profiles contain only what evidence supports. Missing attributes are reported
as unknown/unavailable — never as negative evidence.
"""
from sqlalchemy.orm import Session

from ..models import Person, Entity, Event, Evidence, Relationship, person_entities


def _linked_entities(db: Session, person_id: str):
    rows = (
        db.query(Entity, person_entities.c.role)
        .join(person_entities, person_entities.c.entity_id == Entity.id)
        .filter(person_entities.c.person_id == person_id)
        .all()
    )
    out = {"phone": [], "vehicle": [], "account": [], "location": [], "organization": []}
    for ent, role in rows:
        bucket = out.get(role, [])
        if ent.original_value not in bucket:
            bucket.append(ent.original_value)
    return out


def build_profile(db: Session, person_id: str):
    person = db.get(Person, person_id)
    if not person:
        return None
    ids = _linked_entities(db, person_id)

    cases = []
    for e in db.query(Entity).filter_by(entity_type="CASE", normalized_value=person_id).all():
        cases.append(e.normalized_value)
    # cases derived from events/entities referencing this person
    case_ids = set()
    for e in db.query(Entity).filter(Entity.case_id.isnot(None)).all():
        pass  # covered below via events
    for ev in db.query(Event).filter(
        (Event.person_a_id == person_id) | (Event.person_b_id == person_id)
    ).all():
        if ev.case_id:
            case_ids.add(ev.case_id)
    for ent in db.query(Entity).filter(
        Entity.case_id.isnot(None), Entity.id.in_(
            db.query(person_entities.c.entity_id).filter(person_entities.c.person_id == person_id)
        )
    ).all():
        if ent.case_id:
            case_ids.add(ent.case_id)

    events = db.query(Event).filter(
        (Event.person_a_id == person_id) | (Event.person_b_id == person_id)
    ).order_by(Event.observed_date, Event.observed_time).all()

    relationships = db.query(Relationship).filter(
        (Relationship.person_a_id == person_id) | (Relationship.person_b_id == person_id)
    ).all()

    evidence = db.query(Evidence).filter(
        (Evidence.person_a_id == person_id) | (Evidence.person_b_id == person_id)
    ).all()

    return {
        "person_id": person.id,
        "name": person.name,
        "resolution": person.resolution or {},
        "identifiers": ids,
        "phones": ids["phone"],
        "vehicles": ids["vehicle"],
        "accounts": ids["account"],
        "locations": ids["location"],
        "cases": sorted(case_ids),
        "counts": {
            "phones": len(ids["phone"]),
            "vehicles": len(ids["vehicle"]),
            "accounts": len(ids["account"]),
            "locations": len(ids["location"]),
            "cases": len(case_ids),
            "events": len(events),
            "calls": sum(1 for e in events if e.event_type == "CALL"),
            "transactions": sum(1 for e in events if e.event_type == "TRANSACTION"),
        },
        "events": [
            {
                "id": e.id, "type": e.event_type, "description": e.description,
                "date": e.observed_date, "time": e.observed_time,
                "precision": e.date_precision, "source": e.source_reference,
            }
            for e in events
        ],
        "relationships": [
            {
                "id": r.id,
                "other_person_id": r.person_b_id if r.person_a_id == person_id else r.person_a_id,
                "strength": r.strength, "score": r.score, "decision": r.decision,
            }
            for r in relationships
        ],
        "evidence": [
            {
                "id": e.id, "type": e.type, "source": e.source_reference,
                "date": e.observed_date, "time": e.observed_time, "confidence": e.confidence,
            }
            for e in evidence
        ],
    }
