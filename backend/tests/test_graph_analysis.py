"""Phase 2 graph-analysis tests for the GDS-independent engine."""

from app.services import graph_analysis


def test_graph_contains_case_scoped_nodes_and_relationships(monkeypatch):
    def fake_run(query, parameters=None):
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C1"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CALLED", "score": 0.8},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1"])

    assert set(graph.nodes()) == {"P1", "P2"}
    assert graph["P1"]["P2"]["relationship_type"] == "CALLED"
    assert graph["P1"]["P2"]["score"] == 0.8


def test_metrics_are_deterministic(monkeypatch):
    def fake_run(query, parameters=None):
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C1"},
                {"id": "P3", "name": "C", "case_id": "C1"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CALLED", "score": 1.0},
                {"source": "P2", "target": "P3", "type": "CALLED", "score": 1.0},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1"])
    metrics = graph_analysis._base_metrics(graph)

    assert metrics["degree"]["P2"] == metrics["degree"]["P1"] == metrics["degree"]["P3"]
    assert metrics["betweenness"]["P2"] > metrics["betweenness"]["P1"]
    assert metrics["closeness"]["P2"] > metrics["closeness"]["P1"]


def test_pagerank_returns_all_nodes(monkeypatch):
    def fake_run(query, parameters=None):
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C1"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CALLED", "score": 1.0},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1"])
    pagerank = graph_analysis._pagerank_weighted(graph)

    assert set(pagerank) == {"P1", "P2"}
    assert abs(sum(pagerank.values()) - 1.0) < 1e-9


def test_multi_case_graph_is_supported(monkeypatch):
    def fake_run(query, parameters=None):
        assert parameters == {"case_ids": ["C1", "C2"]}
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C2"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "ASSOCIATED_WITH", "score": 0.9},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1", "C2"])

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1


def test_communities_and_components_are_returned(monkeypatch):
    def fake_run(query, parameters=None):
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C1"},
                {"id": "P3", "name": "C", "case_id": "C1"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CALLED", "score": 1.0},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1"])

    components = graph_analysis._components(graph)
    communities = graph_analysis._communities(graph)

    assert any(row["componentId"] == 0 for row in components)
    assert set(row["entity_id"] for row in communities) == {"P1", "P2", "P3"}


def test_similarity_is_jaccard_over_neighbor_sets(monkeypatch):
    def fake_run(query, parameters=None):
        return [{
            "nodes": [
                {"id": "P1", "name": "A", "case_id": "C1"},
                {"id": "P2", "name": "B", "case_id": "C1"},
                {"id": "P3", "name": "C", "case_id": "C1"},
                {"id": "P4", "name": "D", "case_id": "C1"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CALLED", "score": 1.0},
                {"source": "P1", "target": "P3", "type": "CALLED", "score": 1.0},
                {"source": "P4", "target": "P2", "type": "CALLED", "score": 1.0},
                {"source": "P4", "target": "P3", "type": "CALLED", "score": 1.0},
            ],
        }]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph, _ = graph_analysis._graph(["C1"])
    rows = graph_analysis._similarity(graph)

    pair = next(r for r in rows if {r["entity_a"], r["entity_b"]} == {"P1", "P4"})
    assert pair["similarity"] == 1.0


def test_temporal_summary_supports_multiple_cases():
    from app.services import graph_analysis

    class Event:
        def __init__(self, event_id, event_type, date, time, case_id):
            self.id = event_id
            self.event_type = event_type
            self.observed_date = date
            self.observed_time = time
            self.person_a_id = None
            self.person_b_id = None
            self.case_id = case_id

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                Event("2", "CALL", "2026-09-02", "10:00", "C2"),
                Event("1", "CALL", "2026-09-01", "09:00", "C1"),
            ]

    class DB:
        def query(self, model):
            return Query()

    summary = graph_analysis._temporal_summary(DB(), ["C1", "C2"])
    assert summary["event_count"] == 2
    assert summary["earliest"]["event_id"] == "1"
    assert summary["latest"]["event_id"] == "2"
