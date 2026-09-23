import json
import pytest
from unittest.mock import MagicMock, patch

from app.database import SessionLocal
from app.models import Case, Document, Entity, Event, Evidence, Person, Relationship
from app.services.graph_sync import (
    compute_case_sync_fingerprint,
    sync_case_to_neo4j,
    _prune_case_orphans,
    mark_sync_pending,
)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_fingerprint_computation_and_category_isolation(db):
    case = db.query(Case).first()
    assert case is not None

    fp1, cat_hashes1 = compute_case_sync_fingerprint(db, case.id)
    assert len(fp1) == 24
    assert "case" in cat_hashes1
    assert "documents" in cat_hashes1
    assert "entities" in cat_hashes1
    assert "events" in cat_hashes1
    assert "evidence" in cat_hashes1
    assert "persons" in cat_hashes1
    assert "relationships" in cat_hashes1

    # Idempotent: repeated call gives identical hashes
    fp2, cat_hashes2 = compute_case_sync_fingerprint(db, case.id)
    assert fp1 == fp2
    assert cat_hashes1 == cat_hashes2

    # Mutate only one document
    doc = db.query(Document).filter(Document.case_id == case.id).first()
    if not doc:
        doc = Document(id=f"doc_test_{case.id}", case_id=case.id, filename="test.txt", file_type="txt", status="processed")
        db.add(doc)
        db.commit()

    orig_filename = doc.filename
    try:
        doc.filename = "mutated_filename_for_test.txt"
        db.commit()

        fp_mutated, cat_hashes_mutated = compute_case_sync_fingerprint(db, case.id)
        assert fp_mutated != fp1
        assert cat_hashes_mutated["documents"] != cat_hashes1["documents"]
        # Other categories remain isolated
        assert cat_hashes_mutated["entities"] == cat_hashes1["entities"]
        assert cat_hashes_mutated["events"] == cat_hashes1["events"]
        assert cat_hashes_mutated["case"] == cat_hashes1["case"]
    finally:
        doc.filename = orig_filename
        db.commit()


def test_requirement_a_and_b_full_sync_and_no_change_skip(db, monkeypatch):
    case = db.query(Case).first()
    assert case is not None

    executed_queries = []

    class FakeSession:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute_write(self, fn):
            fake_tx = MagicMock()
            def fake_run(q, **kwargs):
                executed_queries.append(q)
                mock_res = MagicMock()
                mock_res.consume.return_value = None
                return mock_res
            fake_tx.run = fake_run
            fn(fake_tx)

    class FakeDriver:
        def session(self):
            return FakeSession()

    monkeypatch.setattr("app.services.graph_sync.get_driver", lambda: FakeDriver())

    # Mock reconciliation to return a perfect match
    def fake_reconcile(db_sess, cid):
        return {
            "case_id": cid,
            "matched": True,
            "sql": {"persons": 2, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "neo4j": {"persons": 2, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "mismatches": {},
        }
    monkeypatch.setattr("app.services.graph_sync.reconcile_case_in_neo4j", fake_reconcile)

    # Force initial sync (Requirement A: Full case synchronization)
    res1 = sync_case_to_neo4j(db, case.id, force=True)
    assert res1["synced"] is True
    assert case.neo4j_sync_status == "SYNCED"
    assert "_fingerprint" in case.neo4j_sync_counts
    initial_query_count = len(executed_queries)
    assert initial_query_count > 0

    # Second sync with NO changes (Requirement B: A case with no changes does not perform unnecessary work)
    executed_queries.clear()
    res2 = sync_case_to_neo4j(db, case.id, force=False)
    assert res2["status"] == "UP_TO_DATE"
    assert res2["synced"] is False
    assert len(executed_queries) == 0, "No Cypher queries should be executed on an unchanged case!"


def test_requirement_c_incremental_sync_on_single_record_change(db, monkeypatch):
    case = db.query(Case).first()
    assert case is not None

    executed_categories = []

    def mock_sync_case_internal(db_sess, cid, changed_categories=None):
        executed_categories.append(set(changed_categories) if changed_categories else {"ALL"})
        return {"case_id": cid, "persons": 1, "documents": 1, "entities": 1, "events": 1, "evidence": 1, "relationships": 1}

    def fake_reconcile(db_sess, cid):
        return {
            "case_id": cid,
            "matched": True,
            "sql": {"persons": 1, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "neo4j": {"persons": 1, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "mismatches": {},
        }

    monkeypatch.setattr("app.services.graph_sync._sync_case_to_neo4j", mock_sync_case_internal)
    monkeypatch.setattr("app.services.graph_sync.reconcile_case_in_neo4j", fake_reconcile)

    # 1. Establish synced baseline
    sync_case_to_neo4j(db, case.id, force=True)
    assert len(executed_categories) == 1
    assert "ALL" in executed_categories[-1]

    # 2. Modify one document
    doc = db.query(Document).filter(Document.case_id == case.id).first()
    if not doc:
        doc = Document(id=f"doc_inc_{case.id}", case_id=case.id, filename="original.txt", file_type="txt", status="processed")
        db.add(doc)
        db.commit()

    orig_status = doc.status
    try:
        doc.status = "reprocessed"
        db.commit()

        # 3. Synchronize again: should detect changed category and run incremental sync
        executed_categories.clear()
        res = sync_case_to_neo4j(db, case.id, force=False)
        assert res["synced"] is True
        assert res["incremental"] is True
        assert "documents" in res["changed_categories"]
        assert len(executed_categories) == 1
        assert "documents" in executed_categories[0]
    finally:
        doc.status = orig_status
        db.commit()


def test_requirement_d_unrelated_cases_untouched(db):
    cases = db.query(Case).all()
    if len(cases) >= 2:
        case_a, case_b = cases[0], cases[1]
        fp_b_before, _ = compute_case_sync_fingerprint(db, case_b.id)

        # Mutate case_a
        case_a.description = "Updated description for case A only"
        db.commit()

        fp_a, _ = compute_case_sync_fingerprint(db, case_a.id)
        fp_b_after, _ = compute_case_sync_fingerprint(db, case_b.id)

        assert fp_b_before == fp_b_after, "Case B fingerprint must not change when Case A is modified!"


def test_requirement_e_shared_entities_protection_cypher():
    # Verify the Cypher query for pruning identifier entities protects shared nodes
    fake_tx = MagicMock()
    _prune_case_orphans(
        fake_tx,
        case_id="C101",
        expected_doc_ids=[],
        expected_entity_keys=[],
        expected_event_ids=[],
        expected_evidence_ids=[],
        expected_person_ids=[],
    )

    calls = fake_tx.run.call_args_list
    assert len(calls) == 5

    # Check query 4 (identifier entities)
    entity_query = calls[3][0][0]
    assert "WHERE NOT (e)-[:BELONGS_TO]->(:Case)" in entity_query, "Pruning query MUST verify no other Case link exists before deleting entity node"
    assert "DETACH DELETE e" in entity_query

    # Check query 5 (persons)
    person_query = calls[4][0][0]
    assert "WHERE NOT (p)-[:INVOLVED_IN]->(:Case) AND NOT (p)--()" in person_query, "Pruning query MUST protect persons with other relationships or case links"


def test_requirement_f_orphan_pruning_on_deleted_record(db, monkeypatch):
    case = db.query(Case).first()
    assert case is not None

    pruned_docs_args = []
    fake_tx = MagicMock()
    def fake_run(query, **kwargs):
        if "expected_docs" in kwargs:
            pruned_docs_args.append(kwargs["expected_docs"])
        mock_res = MagicMock()
        mock_res.consume.return_value = None
        return mock_res
    fake_tx.run = fake_run

    # 1. Add temporary document
    orphan_doc = Document(id=f"doc_orphan_{case.id}", case_id=case.id, filename="orphan.txt", file_type="txt", status="processed")
    db.add(orphan_doc)
    db.commit()

    docs = db.query(Document).filter(Document.case_id == case.id).all()
    expected_doc_ids_before = [d.id for d in docs]
    assert orphan_doc.id in expected_doc_ids_before

    _prune_case_orphans(fake_tx, case.id, expected_doc_ids_before, [], [], [], [])
    assert orphan_doc.id in pruned_docs_args[-1]

    # 2. Delete document from SQL
    db.delete(orphan_doc)
    db.commit()

    docs_after = db.query(Document).filter(Document.case_id == case.id).all()
    expected_doc_ids_after = [d.id for d in docs_after]
    assert orphan_doc.id not in expected_doc_ids_after

    _prune_case_orphans(fake_tx, case.id, expected_doc_ids_after, [], [], [], [])
    # Now orphan_doc.id is NOT in expected_docs, so Neo4j will delete it
    assert orphan_doc.id not in pruned_docs_args[-1]


def test_requirement_g_idempotency_and_pending_invalidation(db, monkeypatch):
    case = db.query(Case).first()
    assert case is not None

    def fake_reconcile(db_sess, cid):
        return {
            "case_id": cid,
            "matched": True,
            "sql": {"persons": 1, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "neo4j": {"persons": 1, "entities": 1, "documents": 1, "events": 1, "evidence": 1, "relationships": 1},
            "mismatches": {},
        }

    monkeypatch.setattr("app.services.graph_sync._sync_case_to_neo4j", lambda db_sess, cid, changed_categories=None: {})
    monkeypatch.setattr("app.services.graph_sync.reconcile_case_in_neo4j", fake_reconcile)

    # First sync
    res1 = sync_case_to_neo4j(db, case.id, force=True)
    fp1 = case.neo4j_sync_counts.get("_fingerprint")
    assert fp1 is not None

    # Immediate second sync -> returns UP_TO_DATE with identical fingerprint
    res2 = sync_case_to_neo4j(db, case.id)
    assert res2["status"] == "UP_TO_DATE"
    assert res2["fingerprint"] == fp1

    # mark_sync_pending clears cached fingerprint to force re-evaluation on next run
    mark_sync_pending(db, case.id)
    assert case.neo4j_sync_status == "PENDING"
    assert "_fingerprint" not in (case.neo4j_sync_counts or {})
