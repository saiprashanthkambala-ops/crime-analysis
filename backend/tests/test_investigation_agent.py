from app.services.investigation_agent import _fast_tools, _sql_graph_observations


def _context():
    return {
        "cases": [{"id": "C1", "name": "Case One"}, {"id": "C2", "name": "Case Two"}],
        "counts": {"people": 4, "entities": 6, "relationships": 2, "evidence": 5},
        "relationships": [
            {"id": "R1", "person_a": {"id": "P1", "name": "Ravi Kumar"}, "person_b": {"id": "P2", "name": "Suresh Reddy"}, "score": 0.955, "strength": "STRONG"},
            {"id": "R2", "person_a": {"id": "P3", "name": "Arjun Singh"}, "person_b": {"id": "P2", "name": "Suresh Reddy"}, "score": 0.637, "strength": "MODERATE"},
        ],
    }


def test_agent_fast_tool_routes_strongest_relationship():
    result = _fast_tools(_context(), "Which relationship has the strongest score?")
    assert result["tool"] == "relationship_lookup"
    assert result["observations"][0]["id"] == "R1"


def test_agent_fast_tool_routes_suspicious_relationships():
    result = _fast_tools(_context(), "Show suspicious relationships")
    assert result["tool"] == "suspicious_relationships"


def test_sql_graph_observation_ranks_by_weighted_degree():
    result = _sql_graph_observations(_context())
    assert result["ranked_people"][0]["name"] == "Suresh Reddy"
    assert result["ranked_people"][0]["degree"] == 2


def test_agent_fast_tool_routes_counts():
    result = _fast_tools(_context(), "How many people are in this case?")
    assert result["tool"] == "case_summary"
    assert result["observations"]["people"] == 4
