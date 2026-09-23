import pytest

try:
    from scripts.migrate_sqlite_to_postgres import TABLE_ORDER
except ModuleNotFoundError:
    TABLE_ORDER = None

skip_if_no_migration_script = pytest.mark.skipif(
    TABLE_ORDER is None,
    reason="One-time SQLite migration utility was retired after PostgreSQL migration",
)


@skip_if_no_migration_script
def test_migration_order_preserves_foreign_key_dependencies():
    assert TABLE_ORDER.index("users") < TABLE_ORDER.index("cases")
    assert TABLE_ORDER.index("cases") < TABLE_ORDER.index("documents")
    assert TABLE_ORDER.index("documents") < TABLE_ORDER.index("entities")
    assert TABLE_ORDER.index("persons") < TABLE_ORDER.index("events")
    assert TABLE_ORDER.index("evidence") < TABLE_ORDER.index("relationship_evidence")
    assert TABLE_ORDER.index("relationships") < TABLE_ORDER.index("feedback")


@skip_if_no_migration_script
def test_migration_covers_all_application_tables():
    expected = {
        "users", "cases", "case_users", "documents", "processing_jobs",
        "entities", "persons", "person_entities", "events", "evidence",
        "relationships", "relationship_evidence", "feedback", "audit_logs",
    }
    assert expected.issubset(set(TABLE_ORDER))
