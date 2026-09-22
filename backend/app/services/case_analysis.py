"""Case-scoped analysis context built from SQL; Neo4j graph loading is separate."""

import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Case, Entity, Evidence, Event, Person, Relationship, person_entities
from ..security import ensure_case_access
from .neo4j_service import Neo4jConnectionError, run_read_query
from .graph_sync import sync_case_to_neo4j


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
            .order_by(Relationship.score.desc().nullslast())
            .limit(150)
            .all()
        )

    people = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []
    people_by_id = {p.id: p for p in people}

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
        pa = people_by_id.get(r.person_a_id)
        pb = people_by_id.get(r.person_b_id)
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
    max_people: int = 24,
    max_entities: int = 20,
    max_relationships: int = 20,
    max_evidence: int = 16,
    max_chars: int = 9000,
) -> dict:
    """Create a small deterministic context for the hosted model."""
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


def _sql_graph_fallback(db: Session, case_ids: list[str]) -> dict:
    """Build a small graph directly from SQL when Neo4j is unavailable."""
    if not case_ids:
        return {"nodes": [], "edges": []}

    entities = db.query(Entity).filter(Entity.case_id.in_(case_ids)).limit(250).all()
    events = db.query(Event).filter(Event.case_id.in_(case_ids)).limit(250).all()
    evidence = db.query(Evidence).filter(Evidence.case_id.in_(case_ids)).limit(250).all()
    relationships = (
        db.query(Relationship)
        .filter(Relationship.person_a_id.isnot(None), Relationship.person_b_id.isnot(None))
        .limit(500)
        .all()
    )

    person_ids = set()
    for obj in [*events, *evidence]:
        person_ids.update(x for x in (obj.person_a_id, obj.person_b_id) if x)
    for rel in relationships:
        person_ids.update(x for x in (rel.person_a_id, rel.person_b_id) if x)

    people = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []
    nodes = []
    edges = []
    seen_nodes = set()

    def add_node(node_id, label, node_type):
        key = str(node_id)
        if key in seen_nodes:
            return
        seen_nodes.add(key)
        nodes.append({"data": {"id": key, "label": label or key, "type": node_type}})

    for case_id in case_ids:
        case = db.get(Case, case_id)
        add_node(case_id, case.name if case else case_id, "case")

    for person in people:
        add_node(person.id, person.name, "person")
        for ent in getattr(person, "entities", [])[:20]:
            if ent.case_id not in case_ids:
                continue
            ent_id = "entity:" + str(ent.id)
            add_node(ent_id, ent.original_value or ent.normalized_value, str(ent.entity_type or "entity").lower())
            edges.append({
                "data": {
                    "id": f"PE:{person.id}:{ent.id}",
                    "source": str(person.id),
                    "target": ent_id,
                    "label": str(ent.entity_type or "ENTITY"),
                    "type": "ASSOCIATED_WITH",
                }
            })

    for rel in sorted(relationships, key=lambda x: (x.score or 0), reverse=True)[:200]:
        if rel.person_a_id not in seen_nodes and rel.person_b_id not in seen_nodes:
            continue
        edges.append({
            "data": {
                "id": "REL:" + str(rel.id),
                "source": str(rel.person_a_id),
                "target": str(rel.person_b_id),
                "label": f"{rel.strength or 'RELATIONSHIP'} ({(rel.score or 0):.3f})",
                "type": "CONNECTED_TO",
                "score": rel.score,
                "strength": rel.strength,
            }
        })

    for event in events:
        if event.person_a_id and event.person_b_id and event.person_a_id in seen_nodes and event.person_b_id in seen_nodes:
            add_node(event.person_a_id, next((p.name for p in people if p.id == event.person_a_id), event.person_a_id), "person")
            add_node(event.person_b_id, next((p.name for p in people if p.id == event.person_b_id), event.person_b_id), "person")
            event_type = (event.event_type or "EVENT").upper()
            edges.append({
                "data": {
                    "id": "EVENT:" + str(event.id),
                    "source": str(event.person_a_id),
                    "target": str(event.person_b_id),
                    "label": event_type,
                    "type": "CALLED" if event_type == "CALL" else "ASSOCIATED_WITH",
                    "date": event.observed_date,
                    "time": event.observed_time,
                }
            })

    # Deduplicate edges by ID.
    unique_edges = {}
    for edge in edges:
        unique_edges[edge["data"]["id"]] = edge

    return {"nodes": nodes[:500], "edges": list(unique_edges.values())[:800]}


def build_case_graph(db: Session, user, requested_case_ids: list[str] | None = None) -> dict:
    """Synchronize and load the Neo4j graph, with a SQL fallback."""
    case_ids = _case_ids(db, user, requested_case_ids)
    graph = {"nodes": [], "edges": []}
    if not case_ids:
        return {"case_ids": [], "graph": graph, "graph_status": "no_cases"}

    sync_errors = []
    for case_id in case_ids:
        try:
            sync_case_to_neo4j(db, case_id)
        except Exception as exc:
            sync_errors.append(f"{case_id}: {type(exc).__name__}")

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
        if graph["nodes"]:
            return {
                "case_ids": case_ids,
                "graph": graph,
                "graph_status": "connected",
                "graph_sync": {"attempted": len(case_ids), "errors": sync_errors},
            }

        graph = _sql_graph_fallback(db, case_ids)
        return {
            "case_ids": case_ids,
            "graph": graph,
            "graph_status": "sql_fallback_empty_neo4j",
            "graph_sync": {"attempted": len(case_ids), "errors": sync_errors},
        }
    except Neo4jConnectionError as exc:
        graph = _sql_graph_fallback(db, case_ids)
        return {
            "case_ids": case_ids,
            "graph": graph,
            "graph_status": "sql_fallback",
            "graph_error": str(exc),
            "graph_sync": {"attempted": len(case_ids), "errors": sync_errors},
        }
