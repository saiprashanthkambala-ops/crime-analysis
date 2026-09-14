"""Deterministic graph analysis using Neo4j Graph Data Science (GDS).

The service computes measurable network metrics. It does not infer guilt.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..models import Event, Person
from ..security import ensure_case_access
from .neo4j_service import Neo4jConnectionError, run_read_query, run_write_query

GDS_REL_TYPES = ["CONNECTED_TO", "CALLED", "TRANSFERRED_TO", "ASSOCIATED_WITH"]


class GraphAnalysisUnavailable(RuntimeError):
    """Graph analysis is unavailable because GDS/Neo4j is unavailable."""


def _graph_name(case_id: str, directed: bool) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", case_id)[:40]
    return f"crime_analysis_{safe}_{'directed' if directed else 'undirected'}_{uuid.uuid4().hex[:10]}"


def _ensure_gds() -> str:
    try:
        rows = run_read_query("RETURN gds.version() AS version")
    except Exception as exc:  # noqa: BLE001
        raise GraphAnalysisUnavailable("Neo4j Graph Data Science is unavailable.") from exc
    if not rows or not rows[0].get("version"):
        raise GraphAnalysisUnavailable("Neo4j Graph Data Science is unavailable.")
    return str(rows[0]["version"])


def _project_case_graph(case_id: str, *, directed: bool) -> tuple[str, dict[str, Any]]:
    graph_name = _graph_name(case_id, directed)
    orientation_config = [] if directed else ["*"]
    query = """
    MATCH (source:Person)
    WHERE source.case_id = $case_id
    OPTIONAL MATCH (source)-[r]->(target:Person)
    WHERE target.case_id = $case_id
      AND type(r) IN $relationship_types
    WITH source, target, r
    WITH gds.graph.project(
      $graph_name,
      source,
      target,
      {
        sourceNodeLabels: labels(source),
        targetNodeLabels: CASE WHEN target IS NULL THEN [] ELSE labels(target) END,
        relationshipType: CASE WHEN r IS NULL THEN 'REL' ELSE type(r) END,
        relationshipProperties: CASE
          WHEN r IS NULL THEN {weight: 1.0}
          ELSE {weight: CASE WHEN coalesce(r.score, 0.0) > 0.0 THEN r.score ELSE 1.0 END}
        END
      },
      {undirectedRelationshipTypes: $undirected_types}
    ) AS g
    RETURN g.graphName AS graphName, g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount
    """
    try:
        rows = run_read_query(
            query,
            {
                "case_id": case_id,
                "graph_name": graph_name,
                "relationship_types": GDS_REL_TYPES,
                "undirected_types": orientation_config,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise GraphAnalysisUnavailable("Could not project the case graph into Neo4j GDS.") from exc
    if not rows:
        raise GraphAnalysisUnavailable("Neo4j GDS did not return a projected graph.")
    return graph_name, rows[0]


def _drop_graph(graph_name: str) -> None:
    try:
        run_write_query(
            "CALL gds.graph.drop($graph_name, false) YIELD graphName RETURN graphName",
            {"graph_name": graph_name},
        )
    except Exception:
        pass


def _named_nodes_query() -> str:
    return (
        " RETURN gds.util.asNode(nodeId).id AS entity_id, "
        "gds.util.asNode(nodeId).name AS name, score "
        "ORDER BY score DESC, name ASC"
    )


def _centralities(graph_name: str, person_count: int) -> dict[str, Any]:
    sampling = min(person_count, 100)

    degree = run_read_query(
        "CALL gds.degree.stream($graph_name, {orientation: 'UNDIRECTED', relationshipWeightProperty: 'weight', logProgress: false}) YIELD nodeId, score"
        + _named_nodes_query(),
        {"graph_name": graph_name},
    )

    betweenness_cfg = "{logProgress: false}"
    if person_count > 500:
        betweenness_cfg = "{samplingSize: 100, logProgress: false}"

    betweenness = run_read_query(
        f"CALL gds.betweenness.stream($graph_name, {betweenness_cfg}) YIELD nodeId, score"
        + _named_nodes_query(),
        {"graph_name": graph_name},
    )

    closeness = run_read_query(
        "CALL gds.closeness.stream($graph_name, {logProgress: false}) YIELD nodeId, score"
        + _named_nodes_query(),
        {"graph_name": graph_name},
    )

    pagerank = run_read_query(
        "CALL gds.pageRank.stream($graph_name, {maxIterations: 50, dampingFactor: 0.85, relationshipWeightProperty: 'weight', logProgress: false}) YIELD nodeId, score"
        + _named_nodes_query(),
        {"graph_name": graph_name},
    )

    return {
        "degree": degree,
        "betweenness": betweenness,
        "closeness": closeness,
        "pagerank": pagerank,
        "betweenness_mode": "approximate" if person_count > 500 else "exact",
        "betweenness_sampling_size": sampling if person_count > 500 else None,
    }


def _communities(graph_name: str) -> dict[str, Any]:
    louvain = run_read_query(
        "CALL gds.louvain.stream($graph_name, {relationshipWeightProperty: 'weight', logProgress: false}) YIELD nodeId, communityId "
        "RETURN gds.util.asNode(nodeId).id AS entity_id, gds.util.asNode(nodeId).name AS name, communityId "
        "ORDER BY communityId ASC, name ASC",
        {"graph_name": graph_name},
    )
    wcc = run_read_query(
        "CALL gds.wcc.stream($graph_name, {relationshipWeightProperty: 'weight', logProgress: false}) YIELD nodeId, componentId "
        "RETURN gds.util.asNode(nodeId).id AS entity_id, gds.util.asNode(nodeId).name AS name, componentId "
        "ORDER BY componentId ASC, name ASC",
        {"graph_name": graph_name},
    )
    return {"louvain": louvain, "connected_components": wcc}


def _similarity(graph_name: str) -> list[dict[str, Any]]:
    return run_read_query(
        "CALL gds.nodeSimilarity.stream($graph_name, {topK: 5, topN: 50, similarityMetric: 'JACCARD'}) YIELD node1, node2, similarity "
        "RETURN gds.util.asNode(node1).id AS entity_a, gds.util.asNode(node1).name AS name_a, "
        "gds.util.asNode(node2).id AS entity_b, gds.util.asNode(node2).name AS name_b, similarity "
        "ORDER BY similarity DESC, name_a ASC, name_b ASC",
        {"graph_name": graph_name},
    )


def _temporal_summary(db: Session, case_id: str) -> dict[str, Any]:
    events = db.query(Event).filter(Event.case_id == case_id).all()
    ordered = []
    for event in events:
        if event.observed_date or event.observed_time:
            ordered.append(
                {
                    "event_id": str(event.id),
                    "type": event.event_type,
                    "date": event.observed_date,
                    "time": event.observed_time,
                    "person_a_id": event.person_a_id,
                    "person_b_id": event.person_b_id,
                }
            )
    ordered.sort(key=lambda x: ((x["date"] or ""), (x["time"] or ""), x["event_id"]))
    return {
        "event_count": len(events),
        "timed_event_count": len(ordered),
        "earliest": ordered[0] if ordered else None,
        "latest": ordered[-1] if ordered else None,
        "sequence_preview": ordered[:50],
    }


def _multi_hop(case_id: str, person_id: str, max_hops: int) -> list[dict[str, Any]]:
    hops = max(1, min(max_hops, 5))
    query = f"""
    MATCH (source:Person {{id: $person_id}})
    WHERE source.case_id = $case_id
    MATCH p=(source)-[:CONNECTED_TO|CALLED|TRANSFERRED_TO|ASSOCIATED_WITH*1..{hops}]-(target:Person)
    WHERE target.case_id = $case_id AND target.id <> source.id
    WITH target, min(length(p)) AS hops
    RETURN target.id AS entity_id, target.name AS name, hops
    ORDER BY hops ASC, name ASC
    LIMIT 100
    """
    return run_read_query(query, {"case_id": case_id, "person_id": person_id})


def _shortest_path(case_id: str, source_person_id: str, target_person_id: str) -> dict[str, Any]:
    graph_name, _ = _project_case_graph(case_id, directed=True)
    try:
        rows = run_read_query(
            """
            MATCH (s:Person {id: $source_id}), (t:Person {id: $target_id})
            WHERE s.case_id = $case_id AND t.case_id = $case_id
            CALL gds.shortestPath.dijkstra.stream(
              $graph_name,
              {sourceNode: s, targetNode: t}
            )
            YIELD totalCost, nodeIds, path
            RETURN totalCost,
                   [nodeId IN nodeIds | {
                     id: gds.util.asNode(nodeId).id,
                     name: gds.util.asNode(nodeId).name
                   }] AS nodes
            """,
            {
                "graph_name": graph_name,
                "source_id": source_person_id,
                "target_id": target_person_id,
                "case_id": case_id,
            },
        )
        return rows[0] if rows else {"totalCost": None, "nodes": []}
    finally:
        _drop_graph(graph_name)


def analyze_case(db: Session, user, case_id: str) -> dict[str, Any]:
    ensure_case_access(db, user, case_id)

    try:
        people = len(
            run_read_query(
                "MATCH (p:Person) WHERE p.case_id = $case_id RETURN p.id AS id",
                {"case_id": case_id},
            )
        )
    except Neo4jConnectionError as exc:
        raise GraphAnalysisUnavailable("Neo4j is unavailable for graph analysis.") from exc

    version = _ensure_gds()
    undirected_name, projection = _project_case_graph(case_id, directed=False)
    directed_name = None

    try:
        metrics = _centralities(undirected_name, people)
        communities = _communities(undirected_name)
        similarities = _similarity(undirected_name)

        directed_name, _ = _project_case_graph(case_id, directed=True)
        directed_pagerank = run_read_query(
            "CALL gds.pageRank.stream($graph_name, {maxIterations: 50, dampingFactor: 0.85, relationshipWeightProperty: 'weight', logProgress: false}) YIELD nodeId, score "
            "RETURN gds.util.asNode(nodeId).id AS entity_id, gds.util.asNode(nodeId).name AS name, score "
            "ORDER BY score DESC, name ASC",
            {"graph_name": directed_name},
        )
        metrics["pagerank_directed"] = directed_pagerank
    finally:
        _drop_graph(undirected_name)
        if directed_name:
            _drop_graph(directed_name)

    degree_map = {row["entity_id"]: row["score"] for row in metrics["degree"]}
    between_map = {row["entity_id"]: row["score"] for row in metrics["betweenness"]}
    close_map = {row["entity_id"]: row["score"] for row in metrics["closeness"]}
    pr_map = {row["entity_id"]: row["score"] for row in metrics["pagerank"]}
    community_map = {row["entity_id"]: row["communityId"] for row in communities["louvain"]}

    combined = []
    for row in metrics["degree"]:
        eid = row["entity_id"]
        combined.append(
            {
                "entity_id": eid,
                "name": row.get("name") or eid,
                "degree": degree_map.get(eid, 0.0),
                "betweenness": between_map.get(eid, 0.0),
                "closeness": close_map.get(eid, 0.0),
                "pagerank": pr_map.get(eid, 0.0),
                "community_id": community_map.get(eid),
            }
        )
    combined.sort(key=lambda x: (x["pagerank"], x["betweenness"], x["degree"]), reverse=True)

    temporal = _temporal_summary(db, case_id)
    community_sizes: dict[int, int] = {}
    for row in communities["louvain"]:
        cid = row["communityId"]
        community_sizes[cid] = community_sizes.get(cid, 0) + 1

    return {
        "case_id": case_id,
        "gds_version": version,
        "projection": projection,
        "entity_count": people,
        "metrics": {
            "degree_centrality": metrics["degree"],
            "betweenness_centrality": metrics["betweenness"],
            "closeness_centrality": metrics["closeness"],
            "pagerank": metrics["pagerank"],
            "pagerank_directed": metrics["pagerank_directed"],
            "louvain_communities": communities["louvain"],
            "connected_components": communities["connected_components"],
            "node_similarity": similarities,
        },
        "ranked_people": combined[:50],
        "community_sizes": community_sizes,
        "temporal": temporal,
        "betweenness_mode": metrics["betweenness_mode"],
        "betweenness_sampling_size": metrics["betweenness_sampling_size"],
    }


def multi_hop_for_person(db: Session, user, case_id: str, person_id: str, max_hops: int = 3) -> dict[str, Any]:
    ensure_case_access(db, user, case_id)
    rows = _multi_hop(case_id, person_id, max_hops)
    return {
        "case_id": case_id,
        "person_id": person_id,
        "max_hops": max(1, min(max_hops, 5)),
        "neighbors": rows,
    }


def shortest_path_for_people(
    db: Session, user, case_id: str, source_person_id: str, target_person_id: str
) -> dict[str, Any]:
    ensure_case_access(db, user, case_id)
    return {
        "case_id": case_id,
        "source_person_id": source_person_id,
        "target_person_id": target_person_id,
        **_shortest_path(case_id, source_person_id, target_person_id),
    }
