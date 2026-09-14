from app.services.graph_sync import _neo4j_json


def test_neo4j_json_serializes_nested_sql_json():
    value = {"calls": 6, "transactions": [{"amount": 50000}], "location_overlaps": ["Banjara Hills"]}
    encoded = _neo4j_json(value)
    assert isinstance(encoded, str)
    assert '"calls":6' in encoded
    assert '"transactions":[{"amount":50000}]' in encoded


def test_neo4j_json_handles_none():
    assert _neo4j_json(None) is None


def test_neo4j_json_handles_non_json_value():
    assert _neo4j_json(123) == "123"
