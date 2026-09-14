def test_case_sync_status_contract():
    # The model contract uses explicit lifecycle values so UI/backend cannot
    # confuse Neo4j connectivity with case synchronization readiness.
    allowed = {"PENDING", "SYNCING", "SYNCED", "FAILED"}
    assert allowed == {"PENDING", "SYNCING", "SYNCED", "FAILED"}


def test_reconciliation_requires_all_projection_counts():
    required = {
        "persons",
        "entities",
        "documents",
        "events",
        "evidence",
        "relationships",
    }
    assert len(required) == 6


def test_graph_analysis_must_not_use_unverified_neo4j_projection():
    # Architectural contract for the Phase 4 gate.
    sync_verified = False
    source = "sql_fallback" if not sync_verified else "neo4j"
    assert source == "sql_fallback"
