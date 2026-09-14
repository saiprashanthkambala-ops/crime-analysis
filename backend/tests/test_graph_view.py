"""Graph generation regression tests.

The critical invariant is that every selected-case entity node can appear even
when it has no relationship edge yet.
"""

from app.services import graph_view


def test_case_graph_uses_neo4j_complete_node_set(monkeypatch):
    sync_calls = []
    query_calls = []

    def fake_sync(db, case_id):
        sync_calls.append(case_id)
        return {"case_id": case_id}

    def fake_query(query, parameters=None):
        query_calls.append(parameters)
        return [{
            "nodes": [
                {"data": {"id": "C1", "label": "Case One", "type": "case"}},
                {"data": {"id": "P1", "label": "Person One", "type": "person"}},
                {"data": {"id": "phone:999", "label": "999", "type": "phone"}},
            ],
            "edges": [
                {"data": {"id": "e1", "source": "P1", "target": "phone:999", "type": "USES_PHONE", "label": "USES_PHONE"}}
            ],
        }]

    monkeypatch.setattr(graph_view, "sync_case_to_neo4j", fake_sync)
    monkeypatch.setattr(graph_view, "run_read_query", fake_query)
    monkeypatch.setattr(graph_view, "_sql_graph", lambda db, user, ids: {"nodes": [], "edges": [], "source": "sql-fallback", "case_ids": ids})

    result = graph_view.get_case_graph(object(), object(), ["C1"])

    assert result["source"] == "neo4j"
    assert {n["data"]["id"] for n in result["nodes"]} == {"C1", "P1", "phone:999"}
    assert len(result["edges"]) == 1
    assert sync_calls == ["C1"]
    assert query_calls == [{"case_ids": ["C1"]}]


def test_graph_falls_back_when_neo4j_sync_and_read_fail(monkeypatch):
    def fake_sync(db, case_id):
        raise graph_view.Neo4jConnectionError("down")

    monkeypatch.setattr(graph_view, "sync_case_to_neo4j", fake_sync)
    monkeypatch.setattr(
        graph_view,
        "run_read_query",
        lambda query, parameters=None: (_ for _ in ()).throw(graph_view.Neo4jConnectionError("down")),
    )
    fallback = {"nodes": [{"data": {"id": "C1", "label": "Case One", "type": "case"}}], "edges": [], "source": "sql-fallback", "case_ids": ["C1"]}
    monkeypatch.setattr(graph_view, "_sql_graph", lambda db, user, ids: fallback)

    result = graph_view.get_case_graph(object(), object(), ["C1"])

    assert result["source"] == "sql-fallback"
    assert result["case_ids"] == ["C1"]
    assert result["nodes"][0]["data"]["id"] == "C1"
    assert "warning" in result
