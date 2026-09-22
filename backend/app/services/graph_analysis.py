"""Deterministic graph analysis that works with Neo4j without requiring GDS."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from threading import Lock
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


_ANALYSIS_CACHE_TTL_SECONDS = 20.0
_ANALYSIS_CACHE_MAX_ITEMS = 64
_analysis_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_analysis_cache_lock = Lock()


def _get_cached_analysis(case_ids: list[str]) -> dict[str, Any] | None:
    key = tuple(sorted(set(case_ids)))
    now = time.monotonic()
    with _analysis_cache_lock:
        item = _analysis_cache.get(key)
        if item is None:
            return None
        created_at, value = item
        if now - created_at > _ANALYSIS_CACHE_TTL_SECONDS:
            _analysis_cache.pop(key, None)
            return None
        return value


def _set_cached_analysis(case_ids: list[str], value: dict[str, Any]) -> None:
    key = tuple(sorted(set(case_ids)))
    with _analysis_cache_lock:
        _analysis_cache[key] = (time.monotonic(), value)
        if len(_analysis_cache) > _ANALYSIS_CACHE_MAX_ITEMS:
            oldest_key = min(_analysis_cache, key=lambda item: _analysis_cache[item][0])
            _analysis_cache.pop(oldest_key, None)


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


def _pagerank_weighted(graph: nx.Graph, alpha: float = 0.85, max_iter: int = 100, tol: float = 1e-6) -> dict[str, float]:
    if graph.number_of_nodes() == 0:
        return {}
    try:
        return nx.pagerank(graph, weight="score", alpha=alpha, max_iter=max_iter)
    except (ModuleNotFoundError, ImportError, Exception):
        N = len(graph)
        if N == 0:
            return {}
        M = graph.to_directed() if not graph.is_directed() else graph
        x = dict.fromkeys(M, 1.0 / N)
        dangling_nodes = [n for n in M if sum(d.get("score", 1.0) for _, _, d in M.edges(n, data=True)) == 0]
        for _ in range(max_iter):
            xlast = x
            x = dict.fromkeys(xlast.keys(), 0.0)
            danglesum = alpha * sum(xlast[n] for n in dangling_nodes)
            for n in M:
                total_out = sum(d.get("score", 1.0) for _, _, d in M.edges(n, data=True))
                if total_out > 0:
                    for _, nbr, d in M.edges(n, data=True):
                        wt = d.get("score", 1.0)
                        x[nbr] += alpha * xlast[n] * (wt / total_out)
                x[n] += danglesum * (1.0 / N) + (1.0 - alpha) / N
            err = sum(abs(x[n] - xlast[n]) for n in x)
            if err < N * tol:
                break
        s = sum(x.values())
        if s > 0:
            return {k: float(v / s) for k, v in x.items()}
        return {k: float(v) for k, v in x.items()}


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
    """Compute all positive Jaccard similarities without an O(n^2) pair scan.

    A pair can only have non-zero Jaccard similarity when the two nodes share
    at least one neighbor, so generate only those candidate pairs first.
    """
    neighbor_sets = {n: set(graph.neighbors(n)) for n in graph.nodes}
    candidate_pairs: set[tuple[str, str]] = set()

    for neighbors in neighbor_sets.values():
        members = sorted(neighbors)
        # For a hub node, the number of candidate pairs can still be large;
        # cap it to keep interactive analysis predictable.
        if len(members) > 200:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                candidate_pairs.add((a, b))

    rows = []
    for a, b in candidate_pairs:
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
    node_count = graph.number_of_nodes()
    if node_count <= 80:
        betweenness = {
            k: float(v)
            for k, v in nx.betweenness_centrality(graph, normalized=True, weight=None).items()
        }
    else:
        # Exact betweenness is expensive on larger investigation graphs. Use a
        # deterministic bounded sample so interactive analysis stays responsive.
        sample_size = min(64, max(16, int(math.sqrt(node_count) * 4)))
        betweenness = {
            k: float(v)
            for k, v in nx.betweenness_centrality(
                graph,
                k=sample_size,
                normalized=True,
                weight=None,
                seed=42,
            ).items()
        }
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
    """Build a selected-case person graph from SQL relationship rows.

    The Relationship table has no case_id, so selection is derived from
    evidence/events linked to the requested cases. All expensive graph work
    remains local and avoids a Neo4j sync/read during every metrics request.
    """
    from ..models import Evidence, Event, Person, Relationship

    clean_ids = [x for x in case_ids if x]
    if not clean_ids:
        return nx.Graph(), {}

    evidence = (
        db.query(Evidence.person_a_id, Evidence.person_b_id)
        .filter(Evidence.case_id.in_(clean_ids))
        .all()
    )
    events = (
        db.query(Event.person_a_id, Event.person_b_id)
        .filter(Event.case_id.in_(clean_ids))
        .all()
    )
    selected_person_ids = {
        pid
        for pair in [*evidence, *events]
        for pid in pair
        if pid
    }
    if not selected_person_ids:
        return nx.Graph(), {}

    relationships = (
        db.query(Relationship)
        .filter(
            Relationship.person_a_id.in_(selected_person_ids),
            Relationship.person_b_id.in_(selected_person_ids),
            Relationship.person_a_id.isnot(None),
            Relationship.person_b_id.isnot(None),
            Relationship.person_a_id != Relationship.person_b_id,
        )
        .order_by(Relationship.score.desc().nullslast())
        .limit(5000)
        .all()
    )
    if not relationships:
        return nx.Graph(), {}

    related_ids = {
        pid
        for row in relationships
        for pid in (row.person_a_id, row.person_b_id)
        if pid
    }
    people = db.query(Person).filter(Person.id.in_(related_ids)).all()
    people_by_id = {p.id: p for p in people}

    graph = nx.Graph()
    for person in people:
        graph.add_node(person.id, name=person.name or person.id, case_id=None)

    for row in relationships:
        if row.person_a_id not in people_by_id or row.person_b_id not in people_by_id:
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
            "engine": "networkx-local",
            "graph_source": "empty",
            "entity_count": 0,
            "edge_count": 0,
            "metrics": {},
            "ranked_people": [],
            "community_sizes": {},
            "temporal": _temporal_summary(db, []),
            "graph_sync": {"attempted": 0, "errors": []},
        }

    for cid in clean_ids:
        ensure_case_access(db, user, cid)

    cached = _get_cached_analysis(clean_ids)
    if cached is not None:
        return cached

    # SQL is the authoritative relationship store. Calculate metrics directly
    # from it. Neo4j synchronization is a separate explicit operation and must
    # not block the interactive analysis request.
    graph, _ = _sql_person_graph(db, clean_ids)
    graph_source = "sql_authoritative"
    sync_errors: list[str] = []

    if graph.number_of_nodes() == 0:
        return {
            "case_ids": clean_ids,
            "engine": "networkx-local",
            "graph_source": graph_source,
            "gds_version": None,
            "entity_count": 0,
            "edge_count": 0,
            "metrics": {
                "degree_centrality": [],
                "betweenness_centrality": [],
                "closeness_centrality": [],
                "pagerank": [],
                "pagerank_directed": [],
                "louvain_communities": [],
                "connected_components": [],
                "node_similarity": [],
            },
            "ranked_people": [],
            "community_sizes": {},
            "temporal": _temporal_summary(db, clean_ids),
            "graph_sync": {"attempted": len(clean_ids), "errors": sync_errors},
            "betweenness_mode": "exact",
            "betweenness_sampling_size": None,
        }

    metrics = _base_metrics(graph)
    communities = _communities(graph)
    components = _components(graph)
    similarities = _similarity(graph)

    community_sizes: dict[int, int] = defaultdict(int)
    for row in communities:
        community_sizes[row["communityId"]] += 1

    result = {

        "case_ids": clean_ids,
        "engine": "networkx-local",
        "graph_source": graph_source,
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
        "betweenness_mode": "sampled" if graph.number_of_nodes() > 80 else "exact",
        "betweenness_sampling_size": min(64, max(16, int(math.sqrt(graph.number_of_nodes()) * 4))) if graph.number_of_nodes() > 80 else None,
    }
    _set_cached_analysis(clean_ids, result)
    return result

def analyze_case(db: Session, user, case_id: str) -> dict[str, Any]:
    return analyze_cases(db, user, [case_id])


def _multi_hop(case_id: str, person_id: str, max_hops: int) -> list[dict[str, Any]]:
    hops = max(1, min(max_hops, 5))
    query = f"""
    MATCH (source:Person {{id: $person_id}})