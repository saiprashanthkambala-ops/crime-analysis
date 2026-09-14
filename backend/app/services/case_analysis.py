"""Case-scoped analysis context built from SQL and the Neo4j graph."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Case, Entity, Evidence, Event, Person, Relationship
from ..security import ensure_case_access
from .neo4j_service import Neo4jConnectionError, run_read_query


def _case_ids(db: Session, user, requested: list[str] | None) -> list[str]:
    if requested:
        ids = [x.strip() for x in requested if x and x.strip()]
    elif user.role == "admin":
        ids = [c.id for c in db.query(Case).all()]
    else:
        ids = [c.id for c in user.assigned_cases]
    if not ids:
        return []
    for cid in ids:
        ensure_case_access(db, user, cid)
    return ids


def build_case_analysis(db: Session, user, requested_case_ids: list[str] | None = None) -> dict:
    """Build an evidence-grounded context for one or more authorized cases."""
    case_ids = _case_ids(db, user, requested_case_ids)

    cases = db.query(Case).filter(Case.id.in_(case_ids)).all() if case_ids else []
    entities = db.query(Entity).filter(Entity.case_id.in_(case_ids)).all() if case_ids else []
    events = db.query(Event).filter(Event.case_id.in_(case_ids)).all() if case_ids else []
    evidence = db.query(Evidence).filter(Evidence.case_id.in_(case_ids)).all() if case_ids else []

    person_ids = set()
    for e in evidence:
        person_ids.update(x for x in (e.person_a_id, e.person_b_id) if x)
    for e in events:
        person_ids.update(x for x in (e.person_a_id, e.person_b_id) if x)

    relationships = []
    if person_ids:
        relationships = (
            db.query(Relationship)
            .filter(
                Relationship.person_a_id.in_(person_ids),
                Relationship.person_b_id.in_(person_ids),
            )
            .all()
        )

    person_count = (
        db.query(func.count(func.distinct(Person.id)))
        .filter(Person.id.in_(person_ids))
        .scalar()
        if person_ids
        else 0
    )

    summary_cases = [
        {"id": c.id, "name": c.name, "status": c.status, "description": c.description or ""}
        for c in cases
    ]

    entity_rows = [
        {
            "id": e.id,
            "type": e.entity_type,
            "original_value": e.original_value,
            "normalized_value": e.normalized_value,
            "confidence": e.confidence,
            "method": e.extraction_method,
            "source": e.source_reference,
            "document_id": e.source_document_id,
            "date": e.observed_date,
            "time": e.observed_time,
            "case_id": e.case_id,
        }
        for e in entities[:500]
    ]

    relation_rows = []
    for r in sorted(relationships, key=lambda x: (x.score or 0), reverse=True)[:100]:
        pa = db.get(Person, r.person_a_id)
        pb = db.get(Person, r.person_b_id)
        relation_rows.append({
            "id": r.id,
            "person_a": {"id": r.person_a_id, "name": pa.name if pa else r.person_a_id},
            "person_b": {"id": r.person_b_id, "name": pb.name if pb else r.person_b_id},
            "score": r.score,
            "strength": r.strength,
            "signals": r.signals or {},
            "decision": r.decision,
        })

    evidence_rows = [
        {
            "id": e.id,
            "type": e.type,
            "person_a": e.person_a_id,
            "person_b": e.person_b_id,
            "source": e.source_reference,
            "document_id": e.source_document_id,
            "date": e.observed_date,
            "time": e.observed_time,
            "confidence": e.confidence,
            "details": e.details or {},
            "case_id": e.case_id,
        }
        for e in evidence[:500]
    ]

    graph = {"nodes": [], "edges": []}
    graph_status = "unavailable"
    try:
        rows = run_read_query(
            """
            MATCH (c:Case)
            WHERE c.id IN $case_ids
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE (n.case_id IN $case_ids OR n = c)
              AND (m.case_id IN $case_ids OR m = c)
            WITH collect(DISTINCT n) + collect(DISTINCT m) AS raw_nodes,
                 collect(DISTINCT r) AS rels
            UNWIND raw_nodes AS node
            WITH collect(DISTINCT node) AS nodes, rels
            RETURN
              [n IN nodes |
                {data: {
                  id: coalesce(n.id, n.key),
                  label: coalesce(n.name, n.value, n.filename, n.type, n.id, n.key),
                  type: toLower(coalesce(labels(n)[0], "entity")),
                  score: n.score,
                  strength: n.strength
                }}
              ] AS nodes,
              [r IN rels |
                {data: {
                  id: elementId(r),
                  source: coalesce(startNode(r).id, startNode(r).key),
                  target: coalesce(endNode(r).id, endNode(r).key),
                  label: type(r),
                  type: type(r),
                  score: r.score,
                  strength: r.strength
                }}
              ] AS edges
            """,
            {"case_ids": case_ids},
        )
        if rows:
            graph = {"nodes": rows[0].get("nodes", []), "edges": rows[0].get("edges", [])}
        graph_status = "connected"
    except Neo4jConnectionError:
        graph_status = "unavailable"

    return {
        "case_ids": case_ids,
        "cases": summary_cases,
        "counts": {
            "cases": len(cases),
            "people": int(person_count or 0),
            "entities": len(entities),
            "events": len(events),
            "evidence": len(evidence),
            "relationships": len(relationships),
        },
        "entities": entity_rows,
        "relationships": relation_rows,
        "evidence": evidence_rows,
        "graph": graph,
        "graph_status": graph_status,
    }
