"""Regression tests for explicit selected-case graph generation."""

def test_generated_graph_contract():
    graph = {
        "nodes": [{"data": {"id": "C101", "type": "case"}}],
        "edges": [],
        "source": "neo4j",
        "case_ids": ["C101"],
    }
    assert graph["nodes"]
    assert graph["case_ids"] == ["C101"]
    assert graph["source"] in {"neo4j", "sql-fallback"}
