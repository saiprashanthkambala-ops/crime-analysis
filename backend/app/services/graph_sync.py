"""SQLAlchemy -> Neo4j synchronization for Phase 1.

SQLite remains the application system of record. Neo4j receives a case-scoped,
traceable graph projection used by later graph analysis and the AI agent.
"""
from sqlalchemy.orm import Session

from ..models import Case, Document, Entity, Event, Evidence, Person, Relationship, person_entities
from ..services.neo4j_service import get_driver


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


def sync_case_to_neo4j(db: Session, case_id: str) -> dict:
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

            for d in documents:
                _merge_id_node(tx, "Document", d.id, {
                    "id": d.id, "filename": d.filename, "file_type": d.file_type,
                    "status": d.status, "case_id": case_id,
                })
                tx.run(
                    "MATCH (c:Case {id: $case_id}), (d:Document {id: $doc_id}) "
                    "MERGE (d)-[:BELONGS_TO]->(c)", case_id=case_id, doc_id=d.id
                ).consume()

            for p in persons:
                _merge_id_node(tx, "Person", p.id, {
                    "id": p.id, "name": p.name, "resolution": p.resolution or {},
                    "case_id": case_id,
                })
                tx.run(
                    "MATCH (p:Person {id: $person_id}), (c:Case {id: $case_id}) "
                    "MERGE (p)-[:INVOLVED_IN]->(c)", person_id=p.id, case_id=case_id
                ).consume()

            # Identifier entities are case-scoped and keyed by normalized value.
            entity_labels = {
                "PHONE": "Phone", "VEHICLE": "Vehicle", "BANK_ACCOUNT": "BankAccount",
                "LOCATION": "Location",
            }
            for e in entities:
                label = entity_labels.get(e.entity_type)
                if not label:
                    continue
                key = e.normalized_value
                if not key:
                    continue
                _merge_node(tx, label, key, {
                    "key": key, "value": e.original_value, "normalized_value": e.normalized_value,
                    "entity_type": e.entity_type, "case_id": case_id,
                })
                tx.run(
                    f"MATCH (n:{label} {{key: $key}}), (c:Case {{id: $case_id}}) "
                    "MERGE (n)-[:BELONGS_TO]->(c)",
                    key=key, case_id=case_id
                ).consume()

            # Link identifier entities to their canonical persons using the existing association table.
            links = (
                db.query(person_entities.c.person_id, person_entities.c.entity_id, person_entities.c.role)
                .join(Entity, Entity.id == person_entities.c.entity_id)
                .filter(Entity.case_id == case_id)
                .all()
            )
            label_by_entity_id = {e.id: entity_labels.get(e.entity_type) for e in entities}
            key_by_entity_id = {e.id: e.normalized_value for e in entities}
            rel_by_role = {"phone": "USES_PHONE", "vehicle": "OWNS_VEHICLE", "account": "OWNS_ACCOUNT", "location": "VISITED"}
            for pid, eid, role in links:
                label = label_by_entity_id.get(eid)
                key = key_by_entity_id.get(eid)
                rel_type = rel_by_role.get(role)
                if not label or not key or not rel_type:
                    continue
                tx.run(
                    f"MATCH (p:Person {{id: $pid}}), (n:{label} {{key: $key}}) "
                    f"MERGE (p)-[:{rel_type}]->(n)", pid=pid, key=key
                ).consume()

            for ev in events:
                _merge_id_node(tx, "Event", str(ev.id), {
                    "id": str(ev.id), "type": ev.event_type, "description": ev.description,
                    "date": ev.observed_date, "time": ev.observed_time,
                    "source_document_id": ev.source_document_id, "case_id": case_id,
                })
                tx.run(
                    "MATCH (e:Event {id: $event_id}), (c:Case {id: $case_id}) "
                    "MERGE (e)-[:BELONGS_TO]->(c)",
                    event_id=str(ev.id), case_id=case_id
                ).consume()
                if ev.person_a_id:
                    tx.run(
                        "MATCH (p:Person {id: $pid}), (e:Event {id: $eid}) "
                        "MERGE (p)-[:PARTICIPATED_IN]->(e)", pid=ev.person_a_id, eid=str(ev.id)
                    ).consume()
                if ev.person_b_id and ev.person_b_id != ev.person_a_id:
                    tx.run(
                        "MATCH (p:Person {id: $pid}), (e:Event {id: $eid}) "
                        "MERGE (p)-[:PARTICIPATED_IN]->(e)", pid=ev.person_b_id, eid=str(ev.id)
                    ).consume()
                if ev.person_a_id and ev.person_b_id and ev.person_a_id != ev.person_b_id:
                    event_rel = "CALLED" if ev.event_type == "CALL" else "TRANSFERRED_TO" if ev.event_type == "TRANSACTION" else "ASSOCIATED_WITH"
                    tx.run(
                        f"MATCH (a:Person {{id: $a}}), (b:Person {{id: $b}}) "
                        f"MERGE (a)-[r:{event_rel} {{event_id: $eid}}]->(b) "
                        "SET r.date=$date, r.time=$time, r.source_document_id=$source",
                        a=ev.person_a_id, b=ev.person_b_id, eid=str(ev.id),
                        date=ev.observed_date, time=ev.observed_time, source=ev.source_document_id,
                    ).consume()

            for evd in evidence:
                _merge_id_node(tx, "Evidence", evd.id, {
                    "id": evd.id, "type": evd.type, "confidence": evd.confidence,
                    "source_document_id": evd.source_document_id, "source_reference": evd.source_reference,
                    "date": evd.observed_date, "time": evd.observed_time, "case_id": case_id,
                    "details": evd.details or {},
                })
                tx.run(
                    "MATCH (e:Evidence {id: $evidence_id}), (c:Case {id: $case_id}) "
                    "MERGE (e)-[:BELONGS_TO]->(c)",
                    evidence_id=evd.id, case_id=case_id
                ).consume()
                if evd.person_a_id:
                    tx.run(
                        "MATCH (p:Person {id: $pid}), (e:Evidence {id: $eid}) "
                        "MERGE (p)-[:SUPPORTED_BY]->(e)", pid=evd.person_a_id, eid=evd.id
                    ).consume()
                if evd.person_b_id and evd.person_b_id != evd.person_a_id:
                    tx.run(
                        "MATCH (p:Person {id: $pid}), (e:Evidence {id: $eid}) "
                        "MERGE (p)-[:SUPPORTED_BY]->(e)", pid=evd.person_b_id, eid=evd.id
                    ).consume()

            for r in relationships:
                if r.person_a_id == r.person_b_id:
                    continue
                a, b = sorted([r.person_a_id, r.person_b_id])
                tx.run(
                    "MATCH (a:Person {id: $a}), (b:Person {id: $b}) "
                    "MERGE (a)-[r:CONNECTED_TO]->(b) "
                    "SET r.relationship_id=$rid, r.score=$score, r.strength=$strength, r.signals=$signals",
                    a=a, b=b, rid=r.id, score=r.score, strength=r.strength, signals=r.signals or {},
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
