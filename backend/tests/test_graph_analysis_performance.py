import networkx as nx

from app.services.graph_analysis import _base_metrics, _similarity


def test_graph_analysis_uses_approximate_betweenness_for_large_graphs():
    graph = nx.path_graph(100)
    nx.set_edge_attributes(graph, 1.0, "score")

    metrics = _base_metrics(graph)

    assert metrics["betweenness_mode"] == "approximate"
    assert metrics["betweenness_sampling_size"] <= 64
    assert set(metrics["betweenness"]) == set(graph.nodes)


def test_similarity_is_bounded_for_large_graphs():
    graph = nx.complete_graph(150)

    rows = _similarity(graph)

    assert len(rows) <= 50
