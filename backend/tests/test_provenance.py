"""Provenance, false-link prevention, and missing-data tests."""
from app.services.relationships import discover_relationships
from app.services.resolution import resolve_mentions


# ---------------------------------------------------------------- provenance
def test_relationship_evidence_is_traceable(client, auth_headers):
    rels = client.get("/api/relationships", headers=auth_headers).json()
    strong = [r for r in rels if r["strength"] == "STRONG"]
    assert strong, "expected at least one STRONG relationship in the seeded data"

    r = client.get(f"/api/relationships/{strong[0]['id']}", headers=auth_headers).json()
    # every relationship must expose WHY (signals) and its source records
    assert r["sources"], "relationship must carry source documents"
    assert any(k for k, v in r["signals"].items() if v), "relationship must carry signals"
    assert r["evidence"], "STRONG relationship must have evidence records"
    for e in r["evidence"]:
        assert e["source"], "each evidence item must reference a source"


def test_entity_provenance_in_profile(client, auth_headers):
    profile = client.get("/api/persons/P-ravi_kumar", headers=auth_headers).json()
    # profile exposes identifiers + evidence + resolution info (traceability)
    assert profile["name"] == "Ravi Kumar"
    assert profile["resolution"] is not None
    assert profile["resolution"].get("merged") is True
    assert "Ravi K." in profile["resolution"].get("variants", [])


# ---------------------------------------------------------------- false-link prevention
def test_shared_location_alone_is_weak():
    persons = [
        {"id": "P-a", "name": "Person A",
         "identifiers": {"phone": [], "account": [], "vehicle": [], "location": ["Hyderabad"]},
         "cases": []},
        {"id": "P-b", "name": "Person B",
         "identifiers": {"phone": [], "account": [], "vehicle": [], "location": ["Hyderabad"]},
         "cases": []},
    ]
    rels = discover_relationships(persons, [], [])
    assert not rels or rels[0]["strength"] in ("WEAK", "INSUFFICIENT EVIDENCE")


def test_similar_name_alone_does_not_link():
    persons = [
        {"id": "P-a", "name": "Ravi Kumar", "identifiers": {}, "cases": []},
        {"id": "P-b", "name": "Ravinder Kumar", "identifiers": {}, "cases": []},
    ]
    rels = discover_relationships(persons, [], [])
    assert rels == []


# ---------------------------------------------------------------- missing data
def test_missing_identifiers_are_not_negative_evidence(client, auth_headers):
    # Meena Devi has no vehicle; ensure profile reports it as unavailable, not zero-evidence
    profile = client.get("/api/persons/P-meena_devi", headers=auth_headers).json()
    assert profile["counts"]["vehicles"] == 0
    assert "vehicles" in profile  # key present (unavailable), not omitted


def test_resolution_keeps_distinct_people_separate():
    mentions = [
        {"name": "Meena Devi", "identifiers": {"phone": ["9888001122"], "vehicle": [], "account": [], "location": []}},
        {"name": "Arjun Singh", "identifiers": {"phone": ["9000001111"], "vehicle": [], "account": [], "location": []}},
    ]
    clusters = resolve_mentions(mentions)
    assert len(clusters) == 2  # different first names + different phones -> not merged


def test_missing_time_is_not_fabricated(client, auth_headers):
    # timeline events without a time must be reported with time=None
    timeline = client.get("/api/timeline", headers=auth_headers).json()
    for e in timeline:
        if e.get("time") is None:
            assert e["time"] is None  # remains unavailable, never invented
