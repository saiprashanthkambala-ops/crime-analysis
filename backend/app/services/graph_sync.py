"""SQLAlchemy -> Neo4j synchronization for Phase 1.

SQLite remains the application system of record. Neo4j receives a case-scoped,
traceable graph projection used by later graph analysis and the AI agent.
"""
import hashlib
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


def _prune_case_orphans(
    tx,
    case_id: str,
    expected_doc_ids: list[str],
    expected_entity_keys: list[str],
    expected_event_ids: list,
    expected_evidence_ids: list[str],
    expected_person_ids: list[str],
    prune_categories: set[str] | None = None,
) -> None:
    """Safely remove orphaned Neo4j nodes and edges strictly scoped to case_id.

    PostgreSQL is authoritative. Nodes or relationships belonging to other
    cases are strictly preserved and never deleted.
    """
    # 1. Documents belonging to this case not in SQL
    if prune_categories is None or "documents" in prune_categories:
        tx.run(
            """
            MATCH (d:Document)-[r:BELONGS_TO]->(c:Case {id: $case_id})
            WHERE NOT d.id IN $expected_docs
            DELETE r
            WITH d
            WHERE NOT (d)-[:BELONGS_TO]->(:Case)
            DETACH DELETE d
            """,
            case_id=case_id,
            expected_docs=expected_doc_ids,
        ).consume()

    # 2. Events belonging to this case not in SQL
    if prune_categories is None or "events" in prune_categories:
        tx.run(
            """
            MATCH (ev:Event)-[r:BELONGS_TO]->(c:Case {id: $case_id})
            WHERE NOT ev.id IN $expected_events AND NOT toString(ev.id) IN $expected_events
            DELETE r
            WITH ev
            WHERE NOT (ev)-[:BELONGS_TO]->(:Case)
            DETACH DELETE ev
            """,
            case_id=case_id,
            expected_events=expected_event_ids,
        ).consume()

    # 3. Evidence belonging to this case not in SQL
    if prune_categories is None or "evidence" in prune_categories:
        tx.run(
            """
            MATCH (e:Evidence)-[r:BELONGS_TO]->(c:Case {id: $case_id})
            WHERE NOT e.id IN $expected_evidence
            DELETE r
            WITH e
            WHERE NOT (e)-[:BELONGS_TO]->(:Case)
            DETACH DELETE e
            """,
            case_id=case_id,
            expected_evidence=expected_evidence_ids,
        ).consume()

    # 4. Identifier entities belonging to this case not in SQL
    if prune_categories is None or "entities" in prune_categories:
        tx.run(
            """
            MATCH (e)-[r:BELONGS_TO]->(c:Case {id: $case_id})
            WHERE (e:Phone OR e:Vehicle OR e:BankAccount OR e:Location) AND NOT e.key IN $expected_entities
            DELETE r
            WITH e
            WHERE NOT (e)-[:BELONGS_TO]->(:Case)
            DETACH DELETE e
            """,
            case_id=case_id,
            expected_entities=expected_entity_keys,
        ).consume()

    # 5. Persons linked to this case not in SQL
    if prune_categories is None or "persons" in prune_categories:
        tx.run(
            """
            MATCH (p:Person)-[r:INVOLVED_IN]->(c:Case {id: $case_id})
            WHERE NOT p.id IN $expected_persons
            DELETE r
            WITH p
            WHERE NOT (p)-[:INVOLVED_IN]->(:Case) AND NOT (p)--()
            DELETE p
            """,
            case_id=case_id,
            expected_persons=expected_person_ids,
        ).consume()


def compute_case_sync_fingerprint(db: Session, case_id: str) -> tuple[str, dict[str, str]]:
    """Compute deterministic SHA-256 fingerprints for a case and its individual entity categories."""
    case = db.get(Case, case_id)
    if not case:
        raise ValueError("Case not found")

    category_hashes: dict[str, str] = {}

    # 1. Case metadata
    case_raw = json.dumps([case.id, case.name, case.description or "", case.status or ""], sort_keys=True)
    category_hashes["case"] = hashlib.sha256(case_raw.encode("utf-8")).hexdigest()[:16]

    # 2. Documents
    docs = (
        db.query(Document.id, Document.filename, Document.file_type, Document.status)
        .filter(Document.case_id == case_id)
        .order_by(Document.id)
        .all()
    )
    docs_raw = json.dumps([[str(x) for x in r] for r in docs], sort_keys=True)
    category_hashes["documents"] = hashlib.sha256(docs_raw.encode("utf-8")).hexdigest()[:16]

    # 3. Entities
    entities = (
        db.query(Entity.id, Entity.entity_type, Entity.normalized_value, Entity.original_value)
        .filter(Entity.case_id == case_id)
        .order_by(Entity.id)
        .all()
    )
    entities_raw = json.dumps([[str(x) for x in r] for r in entities], sort_keys=True)
    category_hashes["entities"] = hashlib.sha256(entities_raw.encode("utf-8")).hexdigest()[:16]

    # 4. Events
    events = (
        db.query(
            Event.id, Event.event_type, Event.observed_date, Event.observed_time,
            Event.person_a_id, Event.person_b_id, Event.source_document_id
        )
        .filter(Event.case_id == case_id)
        .order_by(Event.id)
        .all()
    )
    events_raw = json.dumps([[str(x) for x in r] for r in events], sort_keys=True)
    category_hashes["events"] = hashlib.sha256(events_raw.encode("utf-8")).hexdigest()[:16]

    # 5. Evidence
    evidence = (
        db.query(
            Evidence.id, Evidence.type, Evidence.confidence, Evidence.observed_date,
            Evidence.observed_time, Evidence.person_a_id, Evidence.person_b_id,
            Evidence.source_document_id, Evidence.source_reference, Evidence.details
        )
        .filter(Evidence.case_id == case_id)
        .order_by(Evidence.id)
        .all()
    )
    evidence_raw = json.dumps([[str(x) for x in r] for r in evidence], default=str, sort_keys=True)
    category_hashes["evidence"] = hashlib.sha256(evidence_raw.encode("utf-8")).hexdigest()[:16]

    # 6. Persons & Person-Entities
    person_ids = set()
    for e in evidence:
        person_ids.update(x for x in (e[5], e[6]) if x)
    for ev in events:
        person_ids.update(x for x in (ev[4], ev[5]) if x)

    linked_rows = (
        db.query(person_entities.c.person_id)
        .join(Entity, Entity.id == person_entities.c.entity_id)
        .filter(Entity.case_id == case_id)
        .distinct()
        .all()
    )
    person_ids.update(row[0] for row in linked_rows)

    persons = []
    if person_ids:
        persons = (
            db.query(Person.id, Person.name, Person.resolution)
            .filter(Person.id.in_(person_ids))
            .order_by(Person.id)
            .all()
        )
    persons_raw = json.dumps([[str(x) for x in r] for r in persons], default=str, sort_keys=True)
    category_hashes["persons"] = hashlib.sha256(persons_raw.encode("utf-8")).hexdigest()[:16]

    # 7. Relationships
    relationships = []
    if person_ids:
        relationships = (
            db.query(
                Relationship.id, Relationship.person_a_id, Relationship.person_b_id,
                Relationship.score, Relationship.strength, Relationship.signals
            )
            .filter(Relationship.person_a_id.in_(person_ids), Relationship.person_b_id.in_(person_ids))
            .order_by(Relationship.id)
            .all()
        )
    relationships_raw = json.dumps([[str(x) for x in r] for r in relationships], default=str, sort_keys=True)
    category_hashes["relationships"] = hashlib.sha256(relationships_raw.encode("utf-8")).hexdigest()[:16]

    # Composite fingerprint
    composite = json.dumps(category_hashes, sort_keys=True)
    fingerprint = hashlib.sha256(composite.encode("utf-8")).hexdigest()[:24]

    return fingerprint, category_hashes


def _sync_case_to_neo4j(db: Session, case_id: str, changed_categories: set[str] | None = None) -> dict:
    """Synchronize one SQL case into Neo4j. Repeated calls are idempotent.

    If changed_categories is specified, only that subset of categories is updated,
    avoiding unnecessary UNWIND writes for unchanged case sections.
    """
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

    entity_labels = {
        "PHONE": "Phone", "VEHICLE": "Vehicle", "BANK_ACCOUNT": "BankAccount",
        "LOCATION": "Location",
    }
    expected_doc_ids = [d.id for d in documents]
    expected_entity_keys = list({
        e.normalized_value for e in entities
        if entity_labels.get(e.entity_type) and e.normalized_value
    })
    expected_event_ids = [str(ev.id) for ev in events] + [ev.id for ev in events if isinstance(ev.id, int)]
    expected_evidence_ids = [evd.id for evd in evidence]
    expected_person_ids = [p.id for p in persons]

    driver = get_driver()
    with driver.session() as session:
        def work(tx):
            _prune_case_orphans(
                tx,
                case.id,
                expected_doc_ids,
                expected_entity_keys,
                expected_event_ids,
                expected_evidence_ids,
                expected_person_ids,
                prune_categories=changed_categories,
            )
            _merge_id_node(tx, "Case", case.id, {
                "id": case.id, "name": case.name, "description": case.description,
                "status": case.status,
            })

            if (changed_categories is None or "documents" in changed_categories) and documents:
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

            if (changed_categories is None or "persons" in changed_categories) and persons:
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
            if changed_categories is None or "entities" in changed_categories or "persons" in changed_categories:
                entity_labels_map = {
                    "PHONE": "Phone", "VEHICLE": "Vehicle", "BANK_ACCOUNT": "BankAccount",
                    "LOCATION": "Location",
                }
                entities_by_label: dict[str, list[dict]] = {}
                for e in entities:
                    label = entity_labels_map.get(e.entity_type)
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
                label_by_entity_id = {e.id: entity_labels_map.get(e.entity_type) for e in entities}
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

            if (changed_categories is None or "events" in changed_categories) and events:
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

            if (changed_categories is None or "evidence" in changed_categories) and evidence:
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

            if (changed_categories is None or "relationships" in changed_categories) and relationships:
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
    if case.neo4j_sync_counts and isinstance(case.neo4j_sync_counts, dict):
        case.neo4j_sync_counts = {k: v for k, v in case.neo4j_sync_counts.items() if not k.startswith("_")}
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


def sync_case_to_neo4j(db: Session, case_id: str, force: bool = False) -> dict:
    """Synchronize a case and verify the resulting Neo4j projection.

    Uses safe content fingerprinting to avoid redundant synchronization writes when
    the SQL authoritative data has not changed.
    """
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError("Case not found")

    fingerprint, category_hashes = compute_case_sync_fingerprint(db, case_id)
    stored_counts = case.neo4j_sync_counts or {}
    stored_fp = stored_counts.get("_fingerprint") if isinstance(stored_counts, dict) else None
    stored_status = case.neo4j_sync_status

    # Fast Short-Circuit: If unchanged and already SYNCED, skip remote Neo4j writes completely!
    if not force and stored_status == "SYNCED" and stored_fp == fingerprint:
        return {
            "case_id": case_id,
            "status": "UP_TO_DATE",
            "synced": False,
            "incremental": True,
            "message": "Graph projection is already up to date with PostgreSQL source of truth.",
            "fingerprint": fingerprint,
            "persons": stored_counts.get("persons", 0),
            "documents": stored_counts.get("documents", 0),
            "entities": stored_counts.get("entities", 0),
            "events": stored_counts.get("events", 0),
            "evidence": stored_counts.get("evidence", 0),
            "relationships": stored_counts.get("relationships", 0),
            "verification": {
                "case_id": case_id,
                "matched": True,
                "sql": {k: stored_counts.get(k, 0) for k in ("persons", "entities", "documents", "events", "evidence", "relationships")},
                "neo4j": {k: stored_counts.get(k, 0) for k in ("persons", "entities", "documents", "events", "evidence", "relationships")},
                "mismatches": {},
            },
        }

    # Determine changed categories for fine-grained sync
    stored_cat_hashes = stored_counts.get("_category_hashes") if isinstance(stored_counts, dict) else {}
    changed_categories = None
    if not force and stored_cat_hashes and stored_status == "SYNCED":
        diff = {cat for cat, h in category_hashes.items() if stored_cat_hashes.get(cat) != h}
        if diff:
            changed_categories = diff
            # If events or evidence changed, also sync persons/relationships to maintain consistency
            if "events" in diff or "evidence" in diff:
                changed_categories.update(["persons", "relationships"])

    case.neo4j_sync_status = "SYNCING"
    case.neo4j_sync_error = None
    db.commit()

    try:
        result = _sync_case_to_neo4j(db, case_id, changed_categories=changed_categories)
        verification = reconcile_case_in_neo4j(db, case_id)

        # Self-healing fallback: If fine-grained sync produced a mismatch, automatically run full sync
        if not verification["matched"] and changed_categories is not None:
            result = _sync_case_to_neo4j(db, case_id, changed_categories=None)
            verification = reconcile_case_in_neo4j(db, case_id)

        if not verification["matched"]:
            case.neo4j_sync_status = "FAILED"
            case.neo4j_sync_error = "Neo4j projection does not match SQL: " + str(verification["mismatches"])
            case.neo4j_sync_counts = {
                **verification["neo4j"],
                "_fingerprint": fingerprint,
                "_category_hashes": category_hashes,
            }
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
        case.neo4j_sync_counts = {
            **verification["neo4j"],
            "_fingerprint": fingerprint,
            "_category_hashes": category_hashes,
        }
        db.commit()
        return {
            **result,
            "synced": True,
            "incremental": (changed_categories is not None),
            "changed_categories": list(changed_categories) if changed_categories else ["ALL"],
            "fingerprint": fingerprint,
            "verification": verification,
        }
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


def prune_case_orphans_in_neo4j(db: Session, case_id: str) -> dict:
    """Explicitly prune orphaned Neo4j nodes and relationships belonging to case_id.

    PostgreSQL is authoritative. Never touches data belonging to another case.
    Returns the reconciliation status after pruning.
    """
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

    entity_labels = {
        "PHONE": "Phone", "VEHICLE": "Vehicle", "BANK_ACCOUNT": "BankAccount",
        "LOCATION": "Location",
    }
    expected_doc_ids = [d.id for d in documents]
    expected_entity_keys = list({
        e.normalized_value for e in entities
        if entity_labels.get(e.entity_type) and e.normalized_value
    })
    expected_event_ids = [str(ev.id) for ev in events] + [ev.id for ev in events if isinstance(ev.id, int)]
    expected_evidence_ids = [evd.id for evd in evidence]
    expected_person_ids = [p.id for p in persons]

    driver = get_driver()
    with driver.session() as session:
        session.execute_write(
            lambda tx: _prune_case_orphans(
                tx,
                case_id,
                expected_doc_ids,
                expected_entity_keys,
                expected_event_ids,
                expected_evidence_ids,
                expected_person_ids,
            )
        )

    return reconcile_case_in_neo4j(db, case_id)

