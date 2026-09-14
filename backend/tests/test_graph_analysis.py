"""Phase 2 graph-analysis tests.

These tests are offline and mock the Neo4j/GDS query layer. Live GDS validation
should be run separately against the configured Neo4j instance.
"""

from app.services import graph_analysis


class FakeQuery:
    def __init__(self, value=0):
        self.value = value

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self.value

    def all(self):
        return []


class FakeDB:
    def query(self, model):
        return FakeQuery(0)


def test_graph_name_is_safe_and_unique():
    first = graph_analysis._graph_name("CASE/001", directed=False)
    second = graph_analysis._graph_name("CASE/001", directed=False)
    assert first != second
    assert first.startswith("crime_analysis_CASE_001_undirected_")


def test_multi_hop_query_is_case_scoped(monkeypatch):
    captured = {}

    def fake_run(query, parameters=None):
        captured["query"] = query
        captured["parameters"] = parameters or {}
        return [{"entity_id": "P2", "name": "Person 2", "hops": 2}]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    rows = graph_analysis._multi_hop("C1", "P1", 3)

    assert rows[0]["entity_id"] == "P2"
    assert captured["parameters"] == {"case_id": "C1", "person_id": "P1"}
    assert "source.case_id = $case_id" in captured["query"]
    assert "target.case_id = $case_id" in captured["query"]
    assert "1..3" in captured["query"]


def test_project_case_graph_uses_only_person_relationships(monkeypatch):
    captured = {}

    def fake_run(query, parameters=None):
        captured["query"] = query
        captured["parameters"] = parameters or {}
        return [{"graphName": "g1", "nodeCount": 3, "relationshipCount": 2}]

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    graph_name, info = graph_analysis._project_case_graph("C1", directed=False)

    assert graph_name == "g1"
    assert info["nodeCount"] == 3
    assert captured["parameters"]["case_id"] == "C1"
    assert captured["parameters"]["relationship_types"] == graph_analysis.GDS_REL_TYPES
    assert captured["parameters"]["undirected_types"] == ["*"]
    assert "source:Person" in captured["query"]
    assert "target:Person" in captured["query"]


def test_centralities_execute_predefined_algorithms(monkeypatch):
    calls = []

    def fake_run(query, parameters=None):
        calls.append(query)
        return []

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    result = graph_analysis._centralities("g1", 10)

    assert set(result) == {
        "degree",
        "betweenness",
        "closeness",
        "pagerank",
        "betweenness_mode",
        "betweenness_sampling_size",
    }
    joined = "
".join(calls)
    assert "gds.degree.stream" in joined
    assert "gds.betweenness.stream" in joined
    assert "gds.closeness.stream" in joined
    assert "gds.pageRank.stream" in joined
    assert result["betweenness_mode"] == "exact"


def test_betweenness_switches_to_sampling_for_large_graph(monkeypatch):
    calls = []

    def fake_run(query, parameters=None):
        calls.append(query)
        return []

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)
    result = graph_analysis._centralities("g1", 501)

    assert result["betweenness_mode"] == "approximate"
    assert result["betweenness_sampling_size"] == 100
    betweenness_calls = [q for q in calls if "gds.betweenness.stream" in q]
    assert betweenness_calls
    assert "samplingSize: 100" in betweenness_calls[0]


def test_community_and_similarity_algorithms_are_predefined(monkeypatch):
    def fake_run(query, parameters=None):
        if "gds.louvain.stream" in query:
            return [{"entity_id": "P1", "name": "A", "communityId": 1}]
        if "gds.wcc.stream" in query:
            return [{"entity_id": "P1", "name": "A", "componentId": 1}]
        if "gds.nodeSimilarity.stream" in query:
            return [{"entity_a": "P1", "name_a": "A", "entity_b": "P2", "name_b": "B", "similarity": 0.5}]
        return []

    monkeypatch.setattr(graph_analysis, "run_read_query", fake_run)

    communities = graph_analysis._communities("g1")
    similarities = graph_analysis._similarity("g1")

    assert communities["louvain"][0]["communityId"] == 1
    assert communities["connected_components"][0]["componentId"] == 1
    assert similarities[0]["similarity"] == 0.5


def test_temporal_summary_is_sorted_and_bounded():
    class Event:
        def __init__(self, event_id, event_type, date, time, a=None, b=None):
            self.id = event_id
            self.event_type = event_type
            self.observed_date = date
            self.observed_time = time
            self.person_a_id = a
            self.person_b_id = b

    class DB:
        def query(self, model):
            return self

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                Event(2, "CALL", "2026-03-02", "10:00"),
                Event(1, "CALL", "2026-03-01", "09:00"),
                Event(3, "NOTE", None, None),
            ]

    summary = graph_analysis._temporal_summary(DB(), "C1")
    assert summary["event_count"] == 3
    assert summary["timed_event_count"] == 2
    assert summary["earliest"]["event_id"] == "1"
    assert summary["latest"]["event_id"] == "2"
