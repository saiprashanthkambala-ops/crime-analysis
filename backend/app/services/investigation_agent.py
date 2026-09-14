"""Deterministic investigation-agent router.

The agent selects a bounded analysis tool first and uses the LLM only to
explain tool results. Tool outputs are the source of truth.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import Case, Person, Relationship
from ..security import ensure_case_access
from .case_analysis import build_case_analysis
from .graph_analysis import GraphAnalysisUnavailable, analyze_case


class InvestigationToolResult(dict):
    """Structured tool result returned to the AI layer."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _relationship_rows(context: dict) -> list[dict[str, Any]]:
    return context.get("relationships", [])


def _fast_tools(context: dict, question: str) -> InvestigationToolResult | None:
    q = _normalize(question)
    relationships = _relationship_rows(context)
    counts = context.get("counts", {})

    if not relationships and any(
        key in q for key in ("relationship", "connection", "connected", "strongest", "suspicious")
    ):
        return InvestigationToolResult(
            tool="relationship_lookup",
            status="no_data",
            observations=["No relationship records were found in the selected case data."],
        )

    if any(x in q for x in ("strongest relationship", "highest relationship score", "highest score", "strongest connection")):
        top = max(relationships, key=lambda r: (r.get("score") or 0))
        return InvestigationToolResult(
            tool="relationship_lookup",
            status="ok",
            observations=[top],
        )

    if any(x in q for x in ("suspicious relationship", "suspicious connection", "suspicious relation", "red flag")):
        ranked = sorted(
            relationships,
            key=lambda r: (r.get("score") or 0),
            reverse=True,
        )[:15]
        return InvestigationToolResult(
            tool="suspicious_relationships",
            status="ok",
            observations=ranked,
            note="Candidates are ranked by recorded relationship score. This is an investigation-prioritization signal, not a finding of guilt.",
        )

    if any(x in q for x in ("how many people", "number of people")):
        return InvestigationToolResult(
            tool="case_summary",
            status="ok",
            observations={"people": counts.get("people", 0)},
        )

    if any(x in q for x in ("how many relationships", "number of relationships")):
        return InvestigationToolResult(
            tool="case_summary",
            status="ok",
            observations={"relationships": counts.get("relationships", 0)},
        )

    if any(x in q for x in ("how many entities", "number of entities")):
        return InvestigationToolResult(
            tool="case_summary",
            status="ok",
            observations={"entities": counts.get("entities", 0)},
        )

    if any(x in q for x in ("compare", "across the selected cases", "between these cases")):
        by_case = {}
        for case in context.get("cases", []):
            by_case[case["id"]] = {"name": case["name"], "relationships": []}
        for rel in relationships:
            for case_id in by_case:
                by_case[case_id]["relationships"].append(rel)
        return InvestigationToolResult(
            tool="cross_case_relationships",
            status="ok",
            observations=by_case,
            note="Relationships are grouped using the currently authorized selected-case context.",
        )

    return None


def run_investigation_tools(db: Session, user, case_ids: list[str], question: str) -> InvestigationToolResult:
    context = build_case_analysis(db, user, case_ids or None)

    fast = _fast_tools(context, question)
    if fast:
        return fast

    q = _normalize(question)
    selected_case = case_ids[0] if len(case_ids) == 1 else None

    if selected_case and any(
        x in q for x in (
            "degree", "centrality", "pagerank", "page rank",
            "betweenness", "closeness", "community", "network",
            "bridge", "cluster", "shortest path", "graph analysis",
        )
    ):
        try:
            result = analyze_case(db, user, selected_case)
            return InvestigationToolResult(
                tool="graph_metrics",
                status="ok",
                case_id=selected_case,
                observations=result,
            )
        except GraphAnalysisUnavailable as exc:
            return InvestigationToolResult(
                tool="graph_metrics",
                status="fallback",
                case_id=selected_case,
                observations=_sql_graph_observations(context),
                note=str(exc),
            )

    return InvestigationToolResult(
        tool="case_context",
        status="ok",
        observations={
            "cases": context.get("cases", []),
            "counts": context.get("counts", {}),
            "relationships": context.get("relationships", [])[:25],
            "evidence": context.get("evidence", [])[:25],
        },
    )


def _sql_graph_observations(context: dict) -> dict[str, Any]:
    """Small deterministic graph metrics from stored relationship rows."""
    rels = context.get("relationships", [])
    degree: dict[str, int] = {}
    weighted: dict[str, float] = {}
    names: dict[str, str] = {}

    adjacency: dict[str, set[str]] = {}
    for r in rels:
        a = r.get("person_a") or {}
        b = r.get("person_b") or {}
        aid = a.get("id")
        bid = b.get("id")
        if not aid or not bid:
            continue
        names[aid] = a.get("name") or aid
        names[bid] = b.get("name") or bid
        degree[aid] = degree.get(aid, 0) + 1
        degree[bid] = degree.get(bid, 0) + 1
        score = float(r.get("score") or 0.0)
        weighted[aid] = weighted.get(aid, 0.0) + score
        weighted[bid] = weighted.get(bid, 0.0) + score
        adjacency.setdefault(aid, set()).add(bid)
        adjacency.setdefault(bid, set()).add(aid)

    people = []
    for pid in sorted(degree, key=lambda p: (-weighted.get(p, 0.0), -degree.get(p, 0), names.get(p, p))):
        people.append({
            "entity_id": pid,
            "name": names.get(pid, pid),
            "degree": degree.get(pid, 0),
            "weighted_degree": round(weighted.get(pid, 0.0), 6),
        })

    return {
        "mode": "sql_relationship_fallback",
        "ranked_people": people[:50],
        "degree_centrality": people[:50],
        "note": "Neo4j GDS was unavailable, so these are deterministic SQL relationship metrics.",
    }
