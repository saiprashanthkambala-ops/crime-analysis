"""Neo4j schema initialization for the Phase 1 graph store."""

from ..services.neo4j_service import run_write_query


CONSTRAINTS = [
    "CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT phone_key_unique IF NOT EXISTS FOR (n:Phone) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT vehicle_key_unique IF NOT EXISTS FOR (n:Vehicle) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT account_key_unique IF NOT EXISTS FOR (n:BankAccount) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT location_key_unique IF NOT EXISTS FOR (n:Location) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (n:Case) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
]


def initialize_schema() -> dict:
    """Create required uniqueness constraints and return a compact result."""
    for query in CONSTRAINTS:
        run_write_query(query)
    return {"constraints_created": len(CONSTRAINTS)}
