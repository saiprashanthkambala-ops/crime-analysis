from app.routers.analysis import _fast_answer, _is_greeting


def _context():
    return {
        "counts": {"people": 4, "entities": 9, "relationships": 3, "evidence": 7},
        "relationships": [
            {
                "id": "R1",
                "person_a": {"id": "P1", "name": "Ravi Kumar"},
                "person_b": {"id": "P2", "name": "Suresh Reddy"},
                "score": 0.955,
                "strength": "STRONG",
                "decision": None,
            },
            {
                "id": "R2",
                "person_a": {"id": "P3", "name": "Arjun Singh"},
                "person_b": {"id": "P2", "name": "Suresh Reddy"},
                "score": 0.637,
                "strength": "MODERATE",
                "decision": None,
            },
        ],
    }


def test_greetings_are_fast_path():
    assert _is_greeting("hii") is True
    assert _is_greeting("hello") is True
    assert _is_greeting("who") is False


def test_strongest_relationship_is_deterministic():
    answer = _fast_answer(_context(), "Which relationship has the highest score?")
    assert "Ravi Kumar" in answer
    assert "Suresh Reddy" in answer
    assert "0.955" in answer


def test_most_connected_is_deterministic():
    answer = _fast_answer(_context(), "Who has the most connections?")
    assert "Suresh Reddy" in answer
    assert "2 relationship links" in answer


def test_counts_are_fast_path():
    assert "4 people" in _fast_answer(_context(), "How many people are in this case?")
    assert "3 relationship records" in _fast_answer(_context(), "How many relationships?")
