"""Unit + integration tests for Crime Analysis core logic."""
import pytest

from app.services.normalization import (
    normalize_phone, normalize_name, normalize_vehicle, normalize_date, normalize_time,
)
from app.services.resolution import resolve_mentions, name_similarity
from app.services.relationships import discover_relationships
from app.services.timeline import build_timeline


# ---------------------------------------------------------------- normalization
def test_normalize_phone():
    assert normalize_phone("+91-98765-43210") == "9876543210"
    assert normalize_phone("0919876543210") == "9876543210"
    assert normalize_phone("9876543210") == "9876543210"


def test_normalize_name():
    assert normalize_name("Ravi Kumar") == "ravi kumar"
    assert normalize_name("  Ravi   Kumar. ") == "ravi kumar"


def test_normalize_vehicle():
    assert normalize_vehicle("TS 09 AB 1234") == "TS09AB1234"
    assert normalize_vehicle("ts09ab1234") == "TS09AB1234"


def test_normalize_date():
    assert normalize_date("20-Aug-2026") == "2026-08-20"
    assert normalize_date("2026-08-20") == "2026-08-20"


def test_normalize_time():
    assert normalize_time("10:15") == "10:15"
    assert normalize_time("2:10 PM") == "14:10"


# ---------------------------------------------------------------- resolution
def test_name_similarity_variants():
    assert name_similarity("Ravi Kumar", "Ravi K.") >= 0.8
    assert name_similarity("Suresh", "Suresh Reddy") >= 0.8
    assert name_similarity("Meena Devi", "Arjun Singh") < 0.8


def test_resolve_merges_variants():
    mentions = [
        {"name": "Ravi Kumar", "identifiers": {"phone": ["9876543210"], "vehicle": [], "account": [], "location": []}},
        {"name": "Ravi K.", "identifiers": {"phone": ["9876543210"], "vehicle": [], "account": [], "location": []}},
        {"name": "Suresh Reddy", "identifiers": {"phone": ["9123456780"], "vehicle": [], "account": [], "location": []}},
    ]
    clusters = resolve_mentions(mentions)
    assert len(clusters) == 2


def test_resolve_canonical_name_tie_is_deterministic():
    # identical mention counts for "Suresh" and "Suresh Reddy" must always pick
    # the most complete spelling (never depend on hash/set iteration order)
    mentions = [
        {"name": "Suresh", "identifiers": {"phone": ["9123456780"], "vehicle": [], "account": [], "location": []}},
        {"name": "Suresh Reddy", "identifiers": {"phone": ["9123456780"], "vehicle": [], "account": [], "location": []}},
    ]
    for _ in range(5):
        clusters = resolve_mentions(mentions)
        assert len(clusters) == 1
        assert clusters[0]["name"] == "Suresh Reddy"


# ---------------------------------------------------------------- relationships
def _person(pid, name, phones=(), accounts=(), vehicles=(), locations=(), cases=()):
    return {"id": pid, "name": name,
            "identifiers": {"phone": list(phones), "account": list(accounts),
                            "vehicle": list(vehicles), "location": list(locations)},
            "cases": list(cases)}


def test_discover_relationship_strength():
    persons = [
        _person("P-a", "Ravi Kumar", phones=["9876543210"], accounts=["5010001234"]),
        _person("P-b", "Suresh Reddy", phones=["9123456780"], accounts=["6020005678"]),
        _person("P-c", "Meena Devi", phones=["9888001122"]),
    ]
    events = []
    for i in range(8):
        events.append({"type": "CALL", "person_a_id": "P-a", "person_b_id": "P-b",
                       "date": "2026-08-20", "source_ref": "CDR.csv"})
    for i in range(2):
        events.append({"type": "TRANSACTION", "person_a_id": "P-a", "person_b_id": "P-b",
                       "date": "2026-08-21", "source_ref": "Txn.json"})
    events.append({"type": "CALL", "person_a_id": "P-a", "person_b_id": "P-c",
                   "date": "2026-08-22", "source_ref": "CDR.csv"})

    rels = discover_relationships(persons, events, [])
    by_pair = {(r["person_a"], r["person_b"]): r for r in rels}
    ab = by_pair[("P-a", "P-b")]
    assert ab["strength"] == "STRONG"
    assert ab["signals"]["calls"] == 8
    assert ab["signals"]["transactions"] == 2


def test_no_relationship_without_signals():
    persons = [
        _person("P-a", "Ravi Kumar"),
        _person("P-b", "Suresh Reddy"),
    ]
    rels = discover_relationships(persons, [], [])
    assert rels == []


def test_shared_identifier_signal():
    persons = [
        _person("P-a", "Ravi Kumar", phones=["9876543210"]),
        _person("P-b", "Suresh Reddy", phones=["9876543210"]),
    ]
    rels = discover_relationships(persons, [], [])
    assert len(rels) == 1
    assert rels[0]["signals"]["shared_identifiers"]


# ---------------------------------------------------------------- timeline
def test_timeline_sorts_and_keeps_missing_time():
    events = [
        {"id": 1, "type": "CALL", "date": "2026-08-20", "time": "10:15", "case_id": "C1"},
        {"id": 2, "type": "TRANSACTION", "date": "2026-08-20", "time": None, "case_id": "C1"},
        {"id": 3, "type": "CALL", "date": "2026-08-19", "time": "09:00", "case_id": "C1"},
    ]
    items = build_timeline(events)
    assert [e["id"] for e in items] == [3, 1, 2]
    # the event with no time sorts last within its day and keeps time=None
    assert items[2]["id"] == 2
    assert items[2]["time"] is None


# ---------------------------------------------------------------- API integration
def test_api_end_to_end():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:  # context manager triggers startup (seeding)
        r = client.post("/api/auth/login", json={"username": "investigator1", "password": "investor1"})
        assert r.status_code == 200
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # unauthorized is rejected
        assert client.get("/api/cases").status_code == 401

        # core endpoints
        assert client.get("/api/admin/stats", headers=h).status_code == 200
        cases = client.get("/api/cases", headers=h).json()
        assert len(cases) >= 1

        persons = client.get("/api/persons", headers=h).json()
        assert any(p["name"] == "Ravi Kumar" for p in persons)

        rels = client.get("/api/relationships", headers=h).json()
        assert any(r["strength"] == "STRONG" for r in rels)

        # search by phone
        s = client.get("/api/search?q=9876543210", headers=h).json()
        assert s["entities"] or s["people"]

        # feedback
        rel_id = rels[0]["id"]
        r = client.post(f"/api/relationships/{rel_id}/feedback", headers=h,
                        json={"decision": "relevant"})
        assert r.status_code == 200

        # audit (admin)
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        admin_tok = r.json()["access_token"]
        audit = client.get("/api/audit", headers={"Authorization": f"Bearer {admin_tok}"}).json()
        assert any(a["action"] == "feedback" for a in audit)
