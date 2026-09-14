"""Deterministic graph analysis that works with Neo4j without requiring GDS."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any

import networkx as nx
from sqlalchemy.orm import Session

from ..security import ensure_case_access
from .neo4j_service import Neo4jConnectionError, run_read_query
from .graph_sync import sync_case_to_neo4j


REL_TYPES = [
    "CONNECTED_TO",
    "CALLED",
    "TRANSFERRED_TO",
    "ASSOCIATED_WITH",
    "TRANSFERRED_MONEY_TO",
    "USES_VEHICLE",
    "VISITED",
]


class GraphAnalysisUnavailable(RuntimeError):
    """Graph analysis data cannot be loaded."""


def _fetch_person_graph(case_ids: list[str]) -> dict[str, Any]:
    if not case_ids:
        return {"nodes": [], "edges": []}

    query = """
    MATCH (p:Person)
    WHERE p.case_id IN $case_ids
    OPTIONAL MATCH (p)-[r]-(q:Person)
    WHERE q.case_id IN $case_ids
    WITH p, q, r
    RETURN
      collect(DISTINCT {
        id: p.id,
        name: coalesce(p.name, p.id),
        case_id: p.case_id
      }) +
      collect(DISTINCT CASE WHEN q IS NULL THEN null ELSE {
        id: q.id,
        name: coalesce(q.name, q.id),
        case_id: q.case_id
      } END) AS nodes,
      collect(DISTINCT CASE WHEN r IS NULL THEN null ELSE {
        source: startNode(r).id,
        target: endNode(r).id,
        type: type(r),
        score: coalesce(r.score, 1.0)
      } END) AS edges
    """
    try:
        rows = run_read_query(query, {"case_ids": case_ids})
    except Neo4jConnectionError as exc:
        raise GraphAnalysisUnavailable("Neo4j is unavailable for graph analysis.") from exc

    if not rows:
        return {"nodes": [], "edges": []}

    raw_nodes = [n for n in rows[0].get("nodes", []) if n]
    raw_edges = [e for e in rows[0].get("edges", []) if e]

    node_map = {n["id"]: n for n in raw_nodes if n.get("id")}
    edge_rows = []
    seen_edges = set()
    for edge in raw_edges:
        source, target = edge.get("source"), edge.get("target")
        if not source or not target or source == target:
            continue
        if source not in node_map or target not in node_map:
            continue
        key = (min(source, target), max(source, target), edge.get("type", "REL"))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edge_rows.append(edge)

    return {"nodes": list(node_map.values()), "edges": edge_rows}


def _graph(case_ids: list[str]) -> tuple[nx.Graph, dict[str, dict]]:
    raw = _fetch_person_graph(case_ids)
    graph = nx.Graph()

    for node in raw["nodes"]:
        graph.add_node(
            node["id"],
            name=node.get("name") or node["id"],
            case_id=node.get("case_id"),
        )

    for edge in raw["edges"]:
        score = edge.get("score")
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 1.0
        if score <= 0:
            score = 1.0
        graph.add_edge(
            edge["source"],
            edge["target"],
            relationship_type=edge.get("type") or "REL",
            score=score,
        )

    return graph, {n: graph.nodes[n] for n in graph.nodes}


def _pagerank_weighted(graph: nx.Graph) -> dict[str, float]:
    if graph.number_of_nodes() == 0:
        return {}
    return nx.pagerank(graph, weight="score", alpha=0.85, max_iter=100)


def _communities(graph: nx.Graph) -> list[dict[str, Any]]:
    if graph.number_of_nodes() == 0:
        return []
    communities = nx.community.louvain_communities(graph, weight="score", seed=42)
    rows = []
    for idx, members in enumerate(sorted(communities, key=lambda s: min(s))):
        for node_id in sorted(members):
            rows.append({
                "entity_id": node_id,
                "name": graph.nodes[node_id].get("name", node_id),
                "communityId": idx,
            })
    return rows


def _components(graph: nx.Graph) -> list[dict[str, Any]]:
    rows = []
    for idx, members in enumerate(sorted(nx.connected_components(graph), key=lambda s: min(s))):
        for node_id in sorted(members):
            rows.append({
                "entity_id": node_id,
                "name": graph.nodes[node_id].get("name", node_id),
                "componentId": idx,
            })
    return rows


def _similarity(graph: nx.Graph) -> list[dict[str, Any]]:
    rows = []
    nodes = list(graph.nodes())
    neighbor_sets = {n: set(graph.neighbors(n)) for n in nodes}
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            union = neighbor_sets[a] | neighbor_sets[b]
            if not union:
                continue
            value = len(neighbor_sets[a] & neighbor_sets[b]) / len(union)
            if value <= 0:
                continue
            rows.append({
                "entity_a": a,
                "name_a": graph.nodes[a].get("name", a),
                "entity_b": b,
                "name_b": graph.nodes[b].get("name", b),
                "similarity": value,
            })
    rows.sort(key=lambda x: (-x["similarity"], x["name_a"], x["name_b"]))
    return rows[:50]


def _temporal_summary(db: Session, case_ids: list[str]) -> dict[str, Any]:
    if not case_ids:
        return {"event_count": 0, "timed_event_count": 0, "earliest": None, "latest": None, "sequence_preview": []}

    from ..models import Event

    events = db.query(Event).filter(Event.case_id.in_(case_ids)).all()
    ordered = []
    for event in events:
        if event.observed_date or event.observed_time:
            ordered.append({
                "event_id": str(event.id),
                "type": event.event_type,
                "date": event.observed_date,
                "time": event.observed_time,
                "person_a_id": event.person_a_id,
                "person_b_id": event.person_b_id,
                "case_id": event.case_id,
            })
    ordered.sort(key=lambda x: ((x["date"] or ""), (x["time"] or ""), x["event_id"]))
    return {
        "event_count": len(events),
        "timed_event_count": len(ordered),
        "earliest": ordered[0] if ordered else None,
        "latest": ordered[-1] if ordered else None,
        "sequence_preview": ordered[:50],
    }


def _base_metrics(graph: nx.Graph) -> dict[str, dict[str, float]]:
    degree = {k: float(v) for k, v in nx.degree_centrality(graph).items()}
    betweenness = {k: float(v) for k, v in nx.betweenness_centrality(graph, normalized=True, weight=None).items()}
    closeness = {k: float(v) for k, v in nx.closeness_centrality(graph).items()}
    pagerank = _pagerank_weighted(graph)
    return {
        "degree": degree,
        "betweenness": betweenness,
        "closeness": closeness,
        "pagerank": pagerank,
    }


def _metric_rows(graph: nx.Graph, scores: dict[str, float]) -> list[dict[str, Any]]:
    rows = [
        {
            "entity_id": node_id,
            "name": graph.nodes[node_id].get("name", node_id),
            "score": float(score),
        }
        for node_id, score in scores.items()
    ]
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    return rows


def _combined(graph: nx.Graph, metrics: dict[str, dict[str, float]], communities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    community_map = {r["entity_id"]: r["communityId"] for r in communities}
    rows = []
    for node_id in graph.nodes:
        rows.append({
            "entity_id": node_id,
            "name": graph.nodes[node_id].get("name", node_id),
            "degree": metrics["degree"].get(node_id, 0.0),
            "betweenness": metrics["betweenness"].get(node_id, 0.0),
            "closeness": metrics["closeness"].get(node_id, 0.0),
            "pagerank": metrics["pagerank"].get(node_id, 0.0),
            "community_id": community_map.get(node_id),
        })
    rows.sort(key=lambda x: (-x["pagerank"], -x["betweenness"], -x["degree"], x["name"]))
    return rows[:50]


def _sql_person_graph(db: Session, case_ids: list[str]) -> tuple[nx.Graph, dict[str, dict]]:
    """Build a person relationship graph from SQL when Neo4j is empty/unavailable."""
    from ..models import Person, Relationship, Event, Evidence

    clean_ids = [x for x in case_ids if x]
    evidence = db.query(Evidence).filter(Evidence.case_id.in_(clean_ids)).all() if clean_ids else []
    events = db.query(Event).filter(Event.case_id.in_(clean_ids)).all() if clean_ids else []

    person_ids: set[str] = set()
    for row in evidence:
        person_ids.update(x for x in (row.person_a_id, row.person_b_id) if x)
    for row in events:
        person_ids.update(x for x in (row.person_a_id, row.person_b_id) if x)

    relationships = (
        db.query(Relationship)
        .filter(
            Relationship.person_a_id.in_(person_ids),
            Relationship.person_b_id.in_(person_ids),
        )
        .all()
        if person_ids
        else []
    )
    for row in relationships:
        person_ids.update(x for x in (row.person_a_id, row.person_b_id) if x)

    people = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []

    graph = nx.Graph()
    for person in people:
        graph.add_node(person.id, name=person.name or person.id, case_id=None)

    for row in relationships:
        if not row.person_a_id or not row.person_b_id or row.person_a_id == row.person_b_id:
            continue
        score = float(row.score or 1.0)
        if score <= 0:
            score = 1.0
        graph.add_edge(
            row.person_a_id,
            row.person_b_id,
            relationship_type="CONNECTED_TO",
            score=score,
        )

    return graph, {node_id: graph.nodes[node_id] for node_id in graph.nodes}


def analyze_cases(db: Session, user, case_ids: list[str]) -> dict[str, Any]:
    clean_ids = [x.strip() for x in case_ids if x and x.strip()]
    if not clean_ids:
        return {
            "case_ids": [],
            "engine": f"networkx-local ({graph_source})",
            "entity_count": 0,
            "edge_count": 0,
            "metrics": {},
            "ranked_people": [],
            "community_sizes": {},
            "temporal": _temporal_summary(db, []),
        }

    for cid in clean_ids:
        ensure_case_access(db, user, cid)

    graph_source = "neo4j"
    sync_errors = []
    # Keep the graph synchronized with the SQL system of record before reading it.
    for cid in clean_ids:
        try:
            sync_case_to_neo4j(db, cid)
        except Exception as exc:
            sync_errors.append(f"{cid}: {type(exc).__name__}")

    try:
        graph, _ = _graph(clean_ids)
    except GraphAnalysisUnavailable:
        graph, _ = _sql_person_graph(db, clean_ids)
        graph_source = "sql_fallback"

    if graph.number_of_nodes() == 0:
        graph, _ = _sql_person_graph(db, clean_ids)
        if graph.number_of_nodes() > 0:
            graph_source = "sql_fallback_empty_neo4j"

    metrics = _base_metrics(graph)
    communities = _communities(graph)
    components = _components(graph)
    similarities = _similarity(graph)

    community_sizes: dict[int, int] = defaultdict(int)
    for row in communities:
        community_sizes[row["communityId"]] += 1

    return {
        "case_ids": clean_ids,
        "engine": "networkx-local",
        "gds_version": None,
        "entity_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "metrics": {
            "degree_centrality": _metric_rows(graph, metrics["degree"]),
            "betweenness_centrality": _metric_rows(graph, metrics["betweenness"]),
            "closeness_centrality": _metric_rows(graph, metrics["closeness"]),
            "pagerank": _metric_rows(graph, metrics["pagerank"]),
            "pagerank_directed": [],
            "louvain_communities": communities,
            "connected_components": components,
            "node_similarity": similarities,
        },
        "ranked_people": _combined(graph, metrics, communities),
        "community_sizes": dict(community_sizes),
        "temporal": _temporal_summary(db, clean_ids),
        "graph_sync": {"attempted": len(clean_ids), "errors": sync_errors},
        "betweenness_mode": "exact",
        "betweenness_sampling_size": None,
    }


def analyze_case(db: Session, user, case_id: str) -> dict[str, Any]:
    return analyze_cases(db, user, [case_id])


def _multi_hop(case_id: str, person_id: str, max_hops: int) -> list[dict[str, Any]]:
    hops = max(1, min(max_hops, 5))
    query = f"""
    MATCH (source:Person {{id: $person_id}})
    WHERE source.case_id = $case_id
    MATCH p=(source)-[*1..{hops}]-(target:Person)
    WHERE target.case_id = $case_id AND target.id <> source.id
    WITH target, min(length(p)) AS hops
    RETURN target.id AS entity_id, target.name AS name, hops
    ORDER BY hops ASC, name ASC
    LIMIT 100
    """
    try:
        return run_read_query(query, {"case_id": case_id, "person_id": person_id})
    except Neo4jConnectionError as exc:
        raise GraphAnalysisUnavailable("Neo4j is unavailable.") from exc


def multi_hop_for_person(db: Session, user, case_id: str, person_id: str, max_hops: int = 3) -> dict[str, Any]:
    ensure_case_access(db, user, case_id)
    return {
        "case_id": case_id,
        "person_id": person_id,
        "max_hops": max(1, min(max_hops, 5)),
        "neighbors": _multi_hop(case_id, person_id, max_hops),
    }


def _shortest_path(case_id: str, source_person_id: str, target_person_id: str) -> dict[str, Any]:
    query = """
    MATCH (s:Person {id: $source_id}), (t:Person {id: $target_id})
    WHERE s.case_id = $case_id AND t.case_id = $case_id
    MATCH p=shortestPath((s)-[*..20]-(t))
    RETURN [n IN nodes(p) | {id: n.id, name: coalesce(n.name, n.id)}] AS nodes,
           length(p) AS hops
    """
    try:
        rows = run_read_query(
            query,
            {
                "source_id": source_person_id,
                "target_id": target_person_id,
                "case_id": case_id,
            },
        )
    except Neo4jConnectionError as exc:
        raise GraphAnalysisUnavailable("Neo4j is unavailable.") from exc
    if not rows:
        return {"hops": None, "nodes": []}
    return rows[0]


def shortest_path_for_people(db: Session, user, case_id: str, source_person_id: str, target_person_id: str) -> dict[str, Any]:
    ensure_case_access(db, user, case_id)
    return {
        "case_id": case_id,
        "source_person_id": source_person_id,
        "target_person_id": target_person_id,
        **_shortest_path(case_id, source_person_id, target_person_id),
    }
