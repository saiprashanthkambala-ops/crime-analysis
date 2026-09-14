import networkx as nx

from app.services import graph_analysis


def test_analyze_cases_syncs_selected_cases(monkeypatch):
    calls = []

    monkeypatch.setattr(graph_analysis, "ensure_case_access", lambda db, user, cid: None)
    monkeypatch.setattr(graph_analysis, "sync_case_to_neo4j", lambda db, cid: calls.append(cid))

    graph = nx.Graph()
    graph.add_node("P1", name="Ravi Kumar", case_id="C1")
    graph.add_node("P2", name="Suresh Reddy", case_id="C1")
    graph.add_edge("P1", "P2", score=0.955, relationship_type="CONNECTED_TO")
    monkeypatch.setattr(graph_analysis, "_graph", lambda case_ids: (graph, {}))

    class DB:
        def query(self, model):
            raise AssertionError("SQL temporal query is outside this regression test")

    monkeypatch.setattr(graph_analysis, "_temporal_summary", lambda db, ids: {"event_count": 0, "timed_event_count": 0, "earliest": None, "latest": None, "sequence_preview": []})

    result = graph_analysis.analyze_cases(DB(), object(), ["C1"])

    assert calls == ["C1"]
    assert result["entity_count"] == 2
    assert result["edge_count"] == 1
    assert "neo4j" in result["engine"]


def test_empty_neo4j_graph_falls_back_to_sql(monkeypatch):
    monkeypatch.setattr(graph_analysis, "ensure_case_access", lambda db, user, cid: None)
    monkeypatch.setattr(graph_analysis, "sync_case_to_neo4j", lambda db, cid: None)
    monkeypatch.setattr(
        graph_analysis,
        "_graph",
        lambda case_ids: (nx.Graph(), {}),
    )
    fallback = nx.Graph()
    fallback.add_node("P1", name="Ravi Kumar", case_id="C1")
    fallback.add_node("P2", name="Suresh Reddy", case_id="C1")
    fallback.add_edge("P1", "P2", score=0.955, relationship_type="CONNECTED_TO")
    monkeypatch.setattr(graph_analysis, "_sql_person_graph", lambda db, case_ids: (fallback, {}))
    monkeypatch.setattr(graph_analysis, "_temporal_summary", lambda db, ids: {"event_count": 0, "timed_event_count": 0, "earliest": None, "latest": None, "sequence_preview": []})

    class DB:
        pass

    result = graph_analysis.analyze_cases(DB(), object(), ["C1"])

    assert result["entity_count"] == 2
    assert result["edge_count"] == 1
    assert result["engine"].endswith("sql_fallback_empty_neo4j)")


def test_sync_failure_does_not_destroy_sql_fallback(monkeypatch):
    monkeypatch.setattr(graph_analysis, "ensure_case_access", lambda db, user, cid: None)
    def fail_sync(db, cid):
        raise RuntimeError("temporary Neo4j failure")
    monkeypatch.setattr(graph_analysis, "sync_case_to_neo4j", fail_sync)
    monkeypatch.setattr(graph_analysis, "_graph", lambda case_ids: (_ for _ in ()).throw(graph_analysis.GraphAnalysisUnavailable("offline")))

    fallback = nx.Graph()
    fallback.add_node("P1", name="A", case_id="C1")
    fallback.add_node("P2", name="B", case_id="C1")
    fallback.add_edge("P1", "P2", score=0.8, relationship_type="CONNECTED_TO")
    monkeypatch.setattr(graph_analysis, "_sql_person_graph", lambda db, case_ids: (fallback, {}))
    monkeypatch.setattr(graph_analysis, "_temporal_summary", lambda db, ids: {"event_count": 0, "timed_event_count": 0, "earliest": None, "latest": None, "sequence_preview": []})

    result = graph_analysis.analyze_cases(object(), object(), ["C1"])

    assert result["entity_count"] == 2
    assert result["edge_count"] == 1
    assert result["engine"].endswith("sql_fallback)")
    assert result["graph_sync"]["errors"] == ["C1: RuntimeError"]
