"""Case-scoped analysis context built from SQL; Neo4j graph loading is separate."""

import json

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
    """Build a bounded SQL context quickly. Does not query Neo4j."""
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

    people = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []

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
        }
        for e in entities[:150]
    ]

    people_rows = [{"id": p.id, "name": p.name} for p in people[:100]]

    relation_rows = []
    for r in sorted(relationships, key=lambda x: (x.score or 0), reverse=True)[:75]:
        pa = db.get(Person, r.person_a_id)
        pb = db.get(Person, r.person_b_id)
        relation_rows.append(
            {
                "id": r.id,
                "person_a": {"id": r.person_a_id, "name": pa.name if pa else r.person_a_id},
                "person_b": {"id": r.person_b_id, "name": pb.name if pb else r.person_b_id},
                "score": r.score,
                "strength": r.strength,
                "signals": r.signals or {},
                "decision": r.decision,
            }
        )

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
        }
        for e in evidence[:150]
    ]

    return {
        "case_ids": case_ids,
        "cases": [
            {"id": c.id, "name": c.name, "status": c.status, "description": c.description or ""}
            for c in cases
        ],
        "counts": {
            "cases": len(cases),
            "people": len(people),
            "entities": len(entities),
            "events": len(events),
            "evidence": len(evidence),
            "relationships": len(relationships),
        },
        "people": people_rows,
        "entities": entity_rows,
        "relationships": relation_rows,
        "evidence": evidence_rows,
    }


def build_llm_context(
    context: dict,
    *,
    max_cases: int = 5,
    max_people: int = 30,
    max_entities: int = 30,
    max_relationships: int = 25,
    max_evidence: int = 25,
    max_chars: int = 12000,
) -> dict:
    """Create a small deterministic context for the hosted model.

    The UI still receives the full case context; this function only controls
    what is sent to NVIDIA.
    """
    compact = {
        "cases": context.get("cases", [])[:max_cases],
        "counts": context.get("counts", {}),
        "people": context.get("people", [])[:max_people],
        "entities": context.get("entities", [])[:max_entities],
        "relationships": context.get("relationships", [])[:max_relationships],
        "evidence": context.get("evidence", [])[:max_evidence],
    }

    encoded = json.dumps(compact, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= max_chars:
        return compact

    compact["evidence"] = compact["evidence"][:12]
    compact["entities"] = compact["entities"][:15]
    compact["relationships"] = compact["relationships"][:15]
    compact["people"] = compact["people"][:20]
    encoded = json.dumps(compact, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= max_chars:
        return compact

    compact["evidence"] = compact["evidence"][:5]
    compact["entities"] = compact["entities"][:8]
    compact["relationships"] = compact["relationships"][:8]
    compact["people"] = compact["people"][:12]
    return compact


def build_case_graph(db: Session, user, requested_case_ids: list[str] | None = None) -> dict:
    """Load the Neo4j graph separately so it cannot block the LLM request."""
    case_ids = _case_ids(db, user, requested_case_ids)
    graph = {"nodes": [], "edges": []}
    if not case_ids:
        return {"case_ids": [], "graph": graph, "graph_status": "no_cases"}

    try:
        rows = run_read_query(
            """
            MATCH (c:Case)
            WHERE c.id IN $case_ids
            WITH collect(c) AS case_nodes
            UNWIND case_nodes AS c
            OPTIONAL MATCH (c)<-[:INVOLVED_IN|BELONGS_TO]-(n)-[r]-(m)
            WHERE (n.case_id IN $case_ids OR n = c)
              AND (m.case_id IN $case_ids OR m = c)
            WITH collect(DISTINCT c) + collect(DISTINCT n) + collect(DISTINCT m) AS raw_nodes,
                 collect(DISTINCT r)[..500] AS rels
            UNWIND raw_nodes AS node
            WITH collect(DISTINCT node)[..500] AS nodes, rels
            RETURN
              [n IN nodes WHERE n IS NOT NULL |
                {data: {
                  id: coalesce(n.id, n.key),
                  label: coalesce(n.name, n.value, n.filename, n.type, n.id, n.key),
                  type: toLower(coalesce(labels(n)[0], "entity")),
                  score: n.score,
                  strength: n.strength
                }}
              ] AS nodes,
              [r IN rels WHERE r IS NOT NULL |
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
        return {"case_ids": case_ids, "graph": graph, "graph_status": "connected"}
    except Neo4jConnectionError as exc:
        return {
            "case_ids": case_ids,
            "graph": graph,
            "graph_status": "unavailable",
            "graph_error": str(exc),
        }
