import networkx as nx

from app.services import graph_analysis


def test_graph_metrics_are_calculated_from_sql_relationships(monkeypatch):
    graph_analysis.clear_analysis_cache()
    graph = nx.Graph()
    graph.add_node("P1", name="Ravi Kumar")
    graph.add_node("P2", name="Suresh Reddy")
    graph.add_node("P3", name="Arjun Singh")
    graph.add_edge("P1", "P2", score=0.955)
    graph.add_edge("P2", "P3", score=0.637)

    monkeypatch.setattr(graph_analysis, "ensure_case_access", lambda db, user, cid: None)
    monkeypatch.setattr(graph_analysis, "_sql_person_graph", lambda db, ids: (graph, {}))
    monkeypatch.setattr(
        graph_analysis,
        "sync_case_to_neo4j",
        lambda db, cid: (_ for _ in ()).throw(RuntimeError("Neo4j unavailable")),
    )
    monkeypatch.setattr(
        graph_analysis,
        "_temporal_summary",
        lambda db, ids: {
            "event_count": 0,
            "timed_event_count": 0,
            "earliest": None,
            "latest": None,
            "sequence_preview": [],
        },
    )

    result = graph_analysis.analyze_cases(object(), object(), ["C101"])

    assert result["graph_source"] == "sql_authoritative"
    assert result["entity_count"] == 3
    assert result["edge_count"] == 2
    assert result["metrics"]["degree_centrality"]


def test_empty_sql_relationship_graph_returns_zero_metrics_without_error(monkeypatch):
    graph_analysis.clear_analysis_cache()
    graph = nx.Graph()
    monkeypatch.setattr(graph_analysis, "ensure_case_access", lambda db, user, cid: None)
    monkeypatch.setattr(graph_analysis, "_sql_person_graph", lambda db, ids: (graph, {}))
    monkeypatch.setattr(graph_analysis, "sync_case_to_neo4j", lambda db, cid: None)
    monkeypatch.setattr(
        graph_analysis,
        "_temporal_summary",
        lambda db, ids: {
            "event_count": 0,
            "timed_event_count": 0,
            "earliest": None,
            "latest": None,
            "sequence_preview": [],
        },
    )

    result = graph_analysis.analyze_cases(object(), object(), ["C101"])

    assert result["entity_count"] == 0
    assert result["edge_count"] == 0
    assert result["ranked_people"] == []
