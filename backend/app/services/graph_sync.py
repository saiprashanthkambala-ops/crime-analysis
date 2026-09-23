"""SQLAlchemy -> Neo4j synchronization for Phase 1.

SQLite remains the application system of record. Neo4j receives a case-scoped,
traceable graph projection used by later graph analysis and the AI agent.
"""
import json

from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable, SessionExpired
from sqlalchemy.orm import Session

from ..models import Case, Document, Entity, Event, Evidence, Person, Relationship, person_entities
from ..services.neo4j_service import Neo4jConnectionError, get_driver, run_read_query



def _neo4j_json(value):
    """Encode arbitrary SQL JSON into a Neo4j-compatible scalar property."""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    except Exception:
        return str(value)


def _merge_node(tx, label, key, props):
    query = f"MERGE (n:{label} {{key: $key}}) SET n += $props RETURN n.key AS key"
    tx.run(query, key=key, props=props).consume()


def _merge_id_node(tx, label, node_id, props):
    query = f"MERGE (n:{label} {{id: $id}}) SET n += $props RETURN n.id AS id"
    tx.run(query, id=node_id, props=props).consume()


def _merge_edge(tx, source_label, source_key, rel_type, target_label, target_key, props=None):
    query = (
        f"MATCH (a:{source_label} {{key: $source_key}}), "
        f"(b:{target_label} {{key: $target_key}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) SET r += $props"
    )
    tx.run(query, source_key=source_key, target_key=target_key, props=props or {}).consume()


def _sync_case_to_neo4j(db: Session, case_id: str) -> dict:
    """Synchronize one SQL case into Neo4j. Repeated calls are idempotent."""
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError("Case not found")

    documents = db.query(Document).filter(Document.case_id == case_id).all()
    entities = db.query(Entity).filter(Entity.case_id == case_id).all()
    events = db.query(Event).filter(Event.case_id == case_id).all()
    evidence = db.query(Evidence).filter(Evidence.case_id == case_id).all()

    person_ids = set()
    for e in evidence:
        person_ids.update(x for x in (e.person_a_id, e.person_b_id) if x)
    for e in events:
        person_ids.update(x for x in (e.person_a_id, e.person_b_id) if x)
    linked_person_rows = (
        db.query(person_entities.c.person_id)
        .join(Entity, Entity.id == person_entities.c.entity_id)
        .filter(Entity.case_id == case_id)
        .distinct()
        .all()
    )
    person_ids.update(row[0] for row in linked_person_rows)
    persons = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []

    relationships = []
    if person_ids:
        relationships = (
            db.query(Relationship)
            .filter(Relationship.person_a_id.in_(person_ids), Relationship.person_b_id.in_(person_ids))
            .all()
        )

    driver = get_driver()
    with driver.session() as session:
        def work(tx):
            _merge_id_node(tx, "Case", case.id, {
                "id": case.id, "name": case.name, "description": case.description,
                "status": case.status,
            })

            if documents:
                doc_batch = [
                    {
                        "id": d.id, "filename": d.filename, "file_type": d.file_type,
                        "status": d.status, "case_id": case_id,
                    }
                    for d in documents
                ]
                tx.run(
                    """
                    UNWIND $batch AS d
                    MERGE (doc:Document {id: d.id})
                    SET doc += d
                    WITH doc
                    MATCH (c:Case {id: $case_id})
                    MERGE (doc)-[:BELONGS_TO]->(c)
                    """,
                    batch=doc_batch, case_id=case_id,
                ).consume()

            if persons:
                person_batch = [
                    {
                        "id": p.id, "name": p.name, "resolution_json": _neo4j_json(p.resolution or {}),
                        "case_id": case_id,
                    }
                    for p in persons
                ]
                tx.run(
                    """
                    UNWIND $batch AS p
                    MERGE (person:Person {id: p.id})
                    SET person += p
                    WITH person
                    MATCH (c:Case {id: $case_id})
                    MERGE (person)-[:INVOLVED_IN]->(c)
                    """,
                    batch=person_batch, case_id=case_id,
                ).consume()

            # Identifier entities are case-scoped and keyed by normalized value.
            entity_labels = {
                "PHONE": "Phone", "VEHICLE": "Vehicle", "BANK_ACCOUNT": "BankAccount",
                "LOCATION": "Location",
            }
            entities_by_label: dict[str, list[dict]] = {}
            for e in entities:
                label = entity_labels.get(e.entity_type)
                if not label or not e.normalized_value:
                    continue
                entities_by_label.setdefault(label, []).append({
                    "key": e.normalized_value, "value": e.original_value,
                    "normalized_value": e.normalized_value,
                    "entity_type": e.entity_type, "case_id": case_id,
                })

            for label, e_batch in entities_by_label.items():
                tx.run(
                    f"""
                    UNWIND $batch AS e
                    MERGE (n:{label} {{key: e.key}})
                    SET n += e
                    WITH n
                    MATCH (c:Case {{id: $case_id}})
                    MERGE (n)-[:BELONGS_TO]->(c)
                    """,
                    batch=e_batch, case_id=case_id,
                ).consume()

            # Link identifier entities to their canonical persons
            links = (
                db.query(person_entities.c.person_id, person_entities.c.entity_id, person_entities.c.role)
                .join(Entity, Entity.id == person_entities.c.entity_id)
                .filter(Entity.case_id == case_id)
                .all()
            )
            label_by_entity_id = {e.id: entity_labels.get(e.entity_type) for e in entities}
            key_by_entity_id = {e.id: e.normalized_value for e in entities}
            rel_by_role = {"phone": "USES_PHONE", "vehicle": "OWNS_VEHICLE", "account": "OWNS_ACCOUNT", "location": "VISITED"}

            links_by_type: dict[tuple[str, str], list[dict]] = {}
            for pid, eid, role in links:
                label = label_by_entity_id.get(eid)
                key = key_by_entity_id.get(eid)
                rel_type = rel_by_role.get(role)
                if not label or not key or not rel_type:
                    continue
                links_by_type.setdefault((label, rel_type), []).append({"pid": pid, "key": key})

            for (label, rel_type), link_batch in links_by_type.items():
                tx.run(
                    f"""
                    UNWIND $batch AS lk
                    MATCH (p:Person {{id: lk.pid}}), (n:{label} {{key: lk.key}})
                    MERGE (p)-[:{rel_type}]->(n)
                    """,
                    batch=link_batch,
                ).consume()

            if events:
                event_batch = [
                    {
                        "id": str(ev.id), "type": ev.event_type, "description": ev.description,
                        "date": ev.observed_date, "time": ev.observed_time,
                        "source_document_id": ev.source_document_id, "case_id": case_id,
                    }
                    for ev in events
                ]
                tx.run(
                    """
                    UNWIND $batch AS ev
                    MERGE (e:Event {id: ev.id})
                    SET e += ev
                    WITH e
                    MATCH (c:Case {id: $case_id})
                    MERGE (e)-[:BELONGS_TO]->(c)
                    """,
                    batch=event_batch, case_id=case_id,
                ).consume()

                participations = []
                direct_event_rels = {}
                for ev in events:
                    eid_str = str(ev.id)
                    if ev.person_a_id:
                        participations.append({"pid": ev.person_a_id, "eid": eid_str})
                    if ev.person_b_id and ev.person_b_id != ev.person_a_id:
                        participations.append({"pid": ev.person_b_id, "eid": eid_str})
                    if ev.person_a_id and ev.person_b_id and ev.person_a_id != ev.person_b_id:
                        rel_type = "CALLED" if ev.event_type == "CALL" else "TRANSFERRED_TO" if ev.event_type == "TRANSACTION" else "ASSOCIATED_WITH"
                        direct_event_rels.setdefault(rel_type, []).append({
                            "a": ev.person_a_id, "b": ev.person_b_id, "eid": eid_str,
                            "date": ev.observed_date, "time": ev.observed_time, "source": ev.source_document_id,
                        })

                if participations:
                    tx.run(
                        """
                        UNWIND $batch AS part
                        MATCH (p:Person {id: part.pid}), (e:Event {id: part.eid})
                        MERGE (p)-[:PARTICIPATED_IN]->(e)
                        """,
                        batch=participations,
                    ).consume()

                for rel_type, r_batch in direct_event_rels.items():
                    tx.run(
                        f"""
                        UNWIND $batch AS r
                        MATCH (a:Person {{id: r.a}}), (b:Person {{id: r.b}})
                        MERGE (a)-[rel:{rel_type} {{event_id: r.eid}}]->(b)
                        SET rel.date = r.date, rel.time = r.time, rel.source_document_id = r.source
                        """,
                        batch=r_batch,
                    ).consume()

            if evidence:
                evidence_batch = [
                    {
                        "id": evd.id, "type": evd.type, "confidence": evd.confidence,
                        "source_document_id": evd.source_document_id, "source_reference": evd.source_reference,
                        "date": evd.observed_date, "time": evd.observed_time, "case_id": case_id,
                        "details_json": _neo4j_json(evd.details or {}),
                    }
                    for evd in evidence
                ]
                tx.run(
                    """
                    UNWIND $batch AS evd
                    MERGE (e:Evidence {id: evd.id})
                    SET e += evd
                    WITH e
                    MATCH (c:Case {id: $case_id})
                    MERGE (e)-[:BELONGS_TO]->(c)
                    """,
                    batch=evidence_batch, case_id=case_id,
                ).consume()

                supports = []
                for evd in evidence:
                    if evd.person_a_id:
                        supports.append({"pid": evd.person_a_id, "eid": evd.id})
                    if evd.person_b_id and evd.person_b_id != evd.person_a_id:
                        supports.append({"pid": evd.person_b_id, "eid": evd.id})

                if supports:
                    tx.run(
                        """
                        UNWIND $batch AS s
                        MATCH (p:Person {id: s.pid}), (e:Evidence {id: s.eid})
                        MERGE (p)-[:SUPPORTED_BY]->(e)
                        """,
                        batch=supports,
                    ).consume()

            if relationships:
                rel_batch = []
                for r in relationships:
                    if r.person_a_id == r.person_b_id:
                        continue
                    a, b = sorted([r.person_a_id, r.person_b_id])
                    rel_batch.append({
                        "a": a, "b": b, "rid": r.id, "score": r.score,
                        "strength": r.strength, "signals": _neo4j_json(r.signals or {}),
                    })
                if rel_batch:
                    tx.run(
                        """
                        UNWIND $batch AS r
                        MATCH (a:Person {id: r.a}), (b:Person {id: r.b})
                        MERGE (a)-[rel:CONNECTED_TO]->(b)
                        SET rel.relationship_id = r.rid, rel.score = r.score,
                            rel.strength = r.strength, rel.signals = r.signals
                        """,
                        batch=rel_batch,
                    ).consume()

        session.execute_write(work)


    return {
        "case_id": case_id,
        "persons": len(persons),
        "documents": len(documents),
        "entities": len(entities),
        "events": len(events),
        "evidence": len(evidence),
        "relationships": len(relationships),
    }


def mark_sync_pending(db: Session, case_id: str) -> None:
    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")
    case.neo4j_sync_status = "PENDING"
    case.neo4j_sync_error = None
    db.commit()


def reconcile_case_in_neo4j(db: Session, case_id: str) -> dict:
    """Compare SQL canonical counts with the Neo4j case projection."""
    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")

    supported_entity_types = ["PHONE", "VEHICLE", "BANK_ACCOUNT", "LOCATION"]
    # Neo4j intentionally projects identifier entities by normalized key, so
    # duplicate source mentions of the same value become one graph node.
    projected_entities = (
        db.query(Entity.entity_type, Entity.normalized_value)
        .filter(
            Entity.case_id == case_id,
            Entity.entity_type.in_(supported_entity_types),
            Entity.normalized_value.isnot(None),
            Entity.normalized_value != "",
        )
        .distinct()
        .all()
    )

    sql_counts = {
        "documents": db.query(Document).filter(Document.case_id == case_id).count(),
        "entities": len(projected_entities),
        "events": db.query(Event).filter(Event.case_id == case_id).count(),
        "evidence": db.query(Evidence).filter(Evidence.case_id == case_id).count(),
    }

    person_ids = set()
    for row in db.query(Event).filter(Event.case_id == case_id).all():
        person_ids.update(x for x in (row.person_a_id, row.person_b_id) if x)
    for row in db.query(Evidence).filter(Evidence.case_id == case_id).all():
        person_ids.update(x for x in (row.person_a_id, row.person_b_id) if x)

    linked = (
        db.query(person_entities.c.person_id)
        .join(Entity, Entity.id == person_entities.c.entity_id)
        .filter(Entity.case_id == case_id)
        .distinct()
        .all()
    )
    person_ids.update(row[0] for row in linked)
    if person_ids:
        sql_counts["persons"] = db.query(Person).filter(Person.id.in_(person_ids)).count()
        relationship_pairs = (
            db.query(Relationship.person_a_id, Relationship.person_b_id)
            .filter(
                Relationship.person_a_id.in_(person_ids),
                Relationship.person_b_id.in_(person_ids),
            )
            .all()
        )
        # Neo4j projects one CONNECTED_TO edge per unordered person pair.
        sql_counts["relationships"] = len({
            tuple(sorted((a, b)))
            for a, b in relationship_pairs
            if a and b and a != b
        })
    else:
        sql_counts["persons"] = 0
        sql_counts["relationships"] = 0

    rows = run_read_query(
        """
        MATCH (c:Case {id: $case_id})
        OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(c)
        WITH c, count(DISTINCT p) AS persons
        OPTIONAL MATCH (e)-[:BELONGS_TO]->(c)
        WHERE e:Phone OR e:Vehicle OR e:BankAccount OR e:Location
        WITH c, persons, count(DISTINCT e) AS entities
        OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(c)
        WITH c, persons, entities, count(DISTINCT d) AS documents
        OPTIONAL MATCH (ev:Event)-[:BELONGS_TO]->(c)
        WITH c, persons, entities, documents, count(DISTINCT ev) AS events
        OPTIONAL MATCH (x:Evidence)-[:BELONGS_TO]->(c)
        WITH c, persons, entities, documents, events, count(DISTINCT x) AS evidence
        OPTIONAL MATCH (a:Person)-[r:CONNECTED_TO]->(b:Person)
        WHERE a.case_id = $case_id AND b.case_id = $case_id
        RETURN count(DISTINCT r) AS relationships,
               persons, entities, documents, events, evidence
        """,
        {"case_id": case_id},
    )

    neo_counts = rows[0] if rows else {
        "persons": 0, "entities": 0, "documents": 0, "events": 0,
        "evidence": 0, "relationships": 0,
    }

    expected = {
        "persons": sql_counts["persons"],
        "entities": sql_counts["entities"],
        "documents": sql_counts["documents"],
        "events": sql_counts["events"],
        "evidence": sql_counts["evidence"],
        "relationships": sql_counts["relationships"],
    }
    actual = {k: int(neo_counts.get(k) or 0) for k in expected}
    mismatches = {
        key: {"sql": expected[key], "neo4j": actual[key]}
        for key in expected
        if expected[key] != actual[key]
    }

    return {
        "case_id": case_id,
        "matched": not mismatches,
        "sql": sql_counts,
        "neo4j": actual,
        "mismatches": mismatches,
    }


def sync_case_to_neo4j(db: Session, case_id: str) -> dict:
    """Synchronize a case and verify the resulting Neo4j projection."""
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError("Case not found")

    case.neo4j_sync_status = "SYNCING"
    case.neo4j_sync_error = None
    db.commit()

    try:
        result = _sync_case_to_neo4j(db, case_id)
        verification = reconcile_case_in_neo4j(db, case_id)
        if not verification["matched"]:
            case.neo4j_sync_status = "FAILED"
            case.neo4j_sync_error = "Neo4j projection does not match SQL: " + str(verification["mismatches"])
            case.neo4j_sync_counts = verification["neo4j"]
            db.commit()
            raise Neo4jConnectionError(
                "Neo4j synchronization verification failed.",
                reason="reconcile_mismatch",
                detail=case.neo4j_sync_error,
            )

        from datetime import datetime
        case.neo4j_sync_status = "SYNCED"
        case.neo4j_sync_at = datetime.utcnow()
        case.neo4j_sync_error = None
        case.neo4j_sync_counts = verification["neo4j"]
        db.commit()
        return {**result, "verification": verification}
    except (Neo4jError, ServiceUnavailable, SessionExpired, DriverError, OSError, TimeoutError, ConnectionError, Neo4jConnectionError, ValueError) as exc:
        case = db.get(Case, case_id)
        if case:
            case.neo4j_sync_status = "FAILED"
            case.neo4j_sync_error = str(exc)[:1000]
            db.commit()
        raise Neo4jConnectionError(
            "Neo4j could not synchronize this case.",
            reason="sync_error",
            detail=str(exc)[:1000],
        ) from exc
    except Exception as exc:
        case = db.get(Case, case_id)
        if case:
            case.neo4j_sync_status = "FAILED"
            case.neo4j_sync_error = str(exc)[:1000]
            db.commit()
        raise
