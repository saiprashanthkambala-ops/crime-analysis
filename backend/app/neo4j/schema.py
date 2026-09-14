"""Neo4j schema initialization for the Phase 1 graph store."""

from ..services.neo4j_service import get_driver


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
    """Create required uniqueness constraints."""
    driver = get_driver()
    with driver.session() as session:
        for query in CONSTRAINTS:
            session.run(query).consume()
    return {"constraints_created": len(CONSTRAINTS)}
