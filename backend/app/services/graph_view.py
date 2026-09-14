"""Case-scoped graph materialization for the UI.

Neo4j is the preferred graph store. Before reading, the selected case(s) are
synchronized from SQL so the visual graph reflects the latest imported data.
If Neo4j is temporarily unavailable, a deterministic SQL graph is returned so
the UI can still render and the failure is visible in metadata.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Case, Document, Entity, Event, Evidence, Person, Relationship, person_entities
from ..security import ensure_case_access
from .graph_sync import sync_case_to_neo4j
from .neo4j_service import Neo4jConfigError, Neo4jConnectionError, run_read_query


ENTITY_LABELS = {
    "PHONE": "phone",
    "VEHICLE": "vehicle",
    "BANK_ACCOUNT": "account",
    "LOCATION": "location",
}
RELATIONSHIP_TYPES = {
    "phone": "USES_PHONE",
    "vehicle": "OWNS_VEHICLE",
    "account": "OWNS_ACCOUNT",
    "location": "VISITED",
}


def _case_ids(db: Session, user, case_ids: list[str] | None) -> list[str]:
    requested = [x.strip() for x in (case_ids or []) if x and x.strip()]
    if requested:
        ids = requested
    elif user.role == "admin":
        ids = [c.id for c in db.query(Case).all()]
    else:
        ids = [c.id for c in user.assigned_cases]
    for cid in ids:
        ensure_case_access(db, user, cid)
    return ids


def _sql_graph(db: Session, user, case_ids: list[str]) -> dict[str, Any]:
    cases = db.query(Case).filter(Case.id.in_(case_ids)).all() if case_ids else []
    documents = db.query(Document).filter(Document.case_id.in_(case_ids)).all() if case_ids else []
    entities = db.query(Entity).filter(Entity.case_id.in_(case_ids)).all() if case_ids else []
    events = db.query(Event).filter(Event.case_id.in_(case_ids)).all() if case_ids else []
    evidence = db.query(Evidence).filter(Evidence.case_id.in_(case_ids)).all() if case_ids else []

    person_ids: set[str] = set()
    for event in events:
        person_ids.update(x for x in (event.person_a_id, event.person_b_id) if x)
    for ev in evidence:
        person_ids.update(x for x in (ev.person_a_id, ev.person_b_id) if x)
    links = (
        db.query(person_entities.c.person_id, person_entities.c.entity_id)
        .join(Entity, Entity.id == person_entities.c.entity_id)
        .filter(Entity.case_id.in_(case_ids))
        .all()
        if case_ids else []
    )
    person_ids.update(pid for pid, _ in links if pid)

    persons = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []
    relationships = (
        db.query(Relationship)
        .filter(
            Relationship.person_a_id.in_(person_ids),
            Relationship.person_b_id.in_(person_ids),
        )
        .all()
        if person_ids else []
    )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, label: str, node_type: str, case_id: str | None = None, **extra):
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({
            "data": {
                "id": node_id,
                "label": label,
                "type": node_type,
                "case_id": case_id,
                **extra,
            }
        })

    for case in cases:
        add_node(case.id, case.name, "case", case.id)

    for person in persons:
        case_id = next(
            (e.case_id for e in entities if e.id in {eid for pid, eid in links if pid == person.id}),
            None,
        )
        add_node(person.id, person.name or person.id, "person", case_id)

    for entity in entities:
        node_type = ENTITY_LABELS.get(entity.entity_type)
        if not node_type or not entity.normalized_value:
            continue
        node_id = f"{node_type}:{entity.normalized_value}"
        add_node(
            node_id,
            entity.original_value or entity.normalized_value,
            node_type,
            entity.case_id,
        )

    for document in documents:
        add_node(document.id, document.filename or document.id, "document", document.case_id)
        edges.append({"data": {
            "id": f"document-case:{document.id}:{document.case_id}",
            "source": document.id,
            "target": document.case_id,
            "type": "BELONGS_TO",
            "label": "BELONGS_TO",
        }})

    for event in events:
        event_id = str(event.id)
        add_node(event_id, event.event_type or event_id, "event", event.case_id)
        for pid in (event.person_a_id, event.person_b_id):
            if pid:
                edges.append({"data": {
                    "id": f"event-person:{event.id}:{pid}",
                    "source": pid,
                    "target": event_id,
                    "type": "PARTICIPATED_IN",
                    "label": "PARTICIPATED_IN",
                }})

    for ev in evidence:
        add_node(ev.id, ev.type or ev.id, "evidence", ev.case_id)
        for pid in (ev.person_a_id, ev.person_b_id):
            if pid:
                edges.append({"data": {
                    "id": f"evidence-person:{ev.id}:{pid}",
                    "source": pid,
                    "target": ev.id,
                    "type": "SUPPORTED_BY",
                    "label": "SUPPORTED_BY",
                }})

    entity_lookup = {e.id: e for e in entities}
    for pid, eid in links:
        entity = entity_lookup.get(eid)
        if not entity or not pid or not entity.normalized_value:
            continue
        node_type = ENTITY_LABELS.get(entity.entity_type)
        if not node_type:
            continue
        node_id = f"{node_type}:{entity.normalized_value}"
        role = next(
            (
                link_role
                for link_pid, link_eid, link_role in db.query(
                    person_entities.c.person_id,
                    person_entities.c.entity_id,
                    person_entities.c.role,
                )
                .filter(person_entities.c.person_id == pid, person_entities.c.entity_id == eid)
                .all()
            ),
            None,
        )
        rel_type = RELATIONSHIP_TYPES.get(role or "", "ASSOCIATED_WITH")
        edges.append({"data": {
            "id": f"entity-link:{pid}:{eid}",
            "source": pid,
            "target": node_id,
            "type": rel_type,
            "label": rel_type,
        }})

    for rel in relationships:
        if not rel.person_a_id or not rel.person_b_id or rel.person_a_id == rel.person_b_id:
            continue
        edges.append({"data": {
            "id": f"relationship:{rel.id}",
            "source": rel.person_a_id,
            "target": rel.person_b_id,
            "type": "CONNECTED_TO",
            "label": "CONNECTED_TO",
            "score": rel.score,
            "strength": rel.strength,
        }})

    return {
        "nodes": nodes,
        "edges": edges,
        "source": "sql-fallback",
        "case_ids": case_ids,
    }


def get_case_graph(db: Session, user, requested_case_ids: list[str] | None = None) -> dict[str, Any]:
    case_ids = _case_ids(db, user, requested_case_ids)
    if not case_ids:
        return {"nodes": [], "edges": [], "case_ids": [], "source": "empty"}

    sync_errors: list[str] = []
    for cid in case_ids:
        try:
            sync_case_to_neo4j(db, cid)
        except Exception as exc:  # noqa: BLE001
            sync_errors.append(f"{cid}: {type(exc).__name__}: {str(exc)[:300]}")

    query = """
    MATCH (c:Case)
    WHERE c.id IN $case_ids
    OPTIONAL MATCH (n)-[:INVOLVED_IN|BELONGS_TO]->(c)
    WITH collect(DISTINCT c) + collect(DISTINCT n) AS direct_nodes
    UNWIND direct_nodes AS d
    WITH collect(DISTINCT d) AS scoped_nodes
    OPTIONAL MATCH (a)-[r]-(b)
    WHERE a IN scoped_nodes AND b IN scoped_nodes
    WITH scoped_nodes, collect(DISTINCT r) AS rels
    RETURN
      [n IN scoped_nodes WHERE n IS NOT NULL | {
        data: {
          id: coalesce(n.id, n.key),
          label: coalesce(n.name, n.value, n.filename, n.type, n.id, n.key),
          type: CASE
            WHEN n:Person THEN "person"
            WHEN n:Phone THEN "phone"
            WHEN n:Vehicle THEN "vehicle"
            WHEN n:BankAccount THEN "account"
            WHEN n:Location THEN "location"
            WHEN n:Case THEN "case"
            WHEN n:Event THEN "event"
            WHEN n:Evidence THEN "evidence"
            WHEN n:Document THEN "document"
            ELSE "entity"
          END,
          score: n.score,
          strength: n.strength,
          case_id: n.case_id
        }
      }] AS nodes,
      [r IN rels WHERE r IS NOT NULL | {
        data: {
          id: elementId(r),
          source: coalesce(startNode(r).id, startNode(r).key),
          target: coalesce(endNode(r).id, endNode(r).key),
          type: type(r),
          label: type(r),
          score: r.score,
          strength: r.strength
        }
      }] AS edges
    """

    try:
        rows = run_read_query(query, {"case_ids": case_ids})
        if rows:
            result = {
                "nodes": rows[0].get("nodes", []),
                "edges": rows[0].get("edges", []),
                "source": "neo4j",
                "case_ids": case_ids,
            }
            if result["nodes"]:
                result["sync_errors"] = sync_errors
                return result
    except Exception as exc:  # noqa: BLE001
        sync_errors.append(f"neo4j_graph_read: {type(exc).__name__}: {str(exc)[:300]}")

    fallback = _sql_graph(db, user, case_ids)
    fallback["sync_errors"] = sync_errors
    fallback["warning"] = "Neo4j graph was unavailable or returned no nodes; displaying the SQL graph projection."
    return fallback
