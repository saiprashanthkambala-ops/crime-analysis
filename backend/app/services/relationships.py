"""Relationship discovery + evidence-strength scoring.

A relationship is produced by combining independent, modular signals. The score
reflects *strength of supporting evidence* — never a probability of guilt.

Events must carry resolved ``person_a_id`` / ``person_b_id`` (the pipeline maps
name variants to canonical person ids before this stage).
"""
from collections import defaultdict
from itertools import combinations

# Per-signal contribution weights (calibrated against the synthetic dataset).
SIGNAL_WEIGHTS = {
    "call": 0.5,
    "transaction": 0.8,
    "location": 0.5,
    "shared_identifier": 1.0,
    "case": 0.4,
}

SCORE_DENOMINATOR = 4.0
INDEPENDENCE_PER_SOURCE = 0.1
MAX_INDEPENDENCE_SOURCES = 3


def _strength_from_score(score):
    if score >= 0.7:
        return "STRONG"
    if score >= 0.45:
        return "MODERATE"
    if score >= 0.2:
        return "WEAK"
    return "INSUFFICIENT EVIDENCE"


def discover_relationships(persons, events, entities):
    """Produce candidate relationships between persons.

    ``persons`` : list of dicts {id, name, identifiers, cases}
    ``events``  : list of dicts with person_a_id/person_b_id/type/date/source
    """
    person_ids = {p["id"] for p in persons}
    signals_by_pair = defaultdict(lambda: {
        "calls": 0, "transactions": 0, "location_overlaps": 0,
        "shared_identifiers": [], "case_overlaps": 0,
        "sources": set(), "dates": [], "evidence": [],
    })

    def key(a, b):
        return tuple(sorted([a, b]))

    def add(a_id, b_id, kind, source, date, detail):
        if not a_id or not b_id or a_id == b_id:
            return
        if a_id not in person_ids or b_id not in person_ids:
            return
        sig = signals_by_pair[key(a_id, b_id)]
        if kind == "call":
            sig["calls"] += 1
        elif kind == "transaction":
            sig["transactions"] += 1
        elif kind == "location":
            sig["location_overlaps"] += 1
        elif kind == "shared_identifier":
            if detail not in sig["shared_identifiers"]:
                sig["shared_identifiers"].append(detail)
        elif kind == "case":
            sig["case_overlaps"] += 1
        if source:
            sig["sources"].add(source)
        if date:
            sig["dates"].append(date)
        sig["evidence"].append({"kind": kind, "source": source, "date": date, "detail": detail})

    # 1. Event-driven signals
    for e in events:
        a, b = e.get("person_a_id"), e.get("person_b_id")
        etype = (e.get("type") or "").upper()
        src = e.get("source_ref") or e.get("source")
        date = e.get("date")
        if etype == "CALL":
            add(a, b, "call", src, date, e.get("description"))
        elif etype == "TRANSACTION":
            add(a, b, "transaction", src, date, e.get("description"))
        elif etype in ("LOCATION_OBSERVATION", "CCTV", "SIGHTING"):
            add(a, b, "location", src, date, e.get("description"))

    # 2. Shared identifiers across persons
    by_id = {p["id"]: p for p in persons}
    for p, q in combinations(persons, 2):
        pi, qi = p.get("identifiers", {}), q.get("identifiers", {})
        for kind, key_name in (("phone", "phone"), ("account", "account"), ("vehicle", "vehicle")):
            for val in set(pi.get(key_name, [])) & set(qi.get(key_name, [])):
                add(p["id"], q["id"], "shared_identifier", None, None, f"shared {key_name} {val}")
        # shared location (only when both were explicitly associated with it)
        for val in set(pi.get("location", [])) & set(qi.get("location", [])):
            add(p["id"], q["id"], "location", None, None, f"shared location {val}")
        # shared cases (only meaningful when a person spans multiple cases)
        common_cases = set(p.get("cases", [])) & set(q.get("cases", []))
        if len(p.get("cases", [])) > 1 or len(q.get("cases", [])) > 1:
            for _ in common_cases:
                add(p["id"], q["id"], "case", None, None, "shared case")

    # 3. Build relationship objects
    name_by_id = {p["id"]: p["name"] for p in persons}
    relationships = []
    for (ida, idb), sig in signals_by_pair.items():
        weighted = (
            sig["calls"] * SIGNAL_WEIGHTS["call"]
            + sig["transactions"] * SIGNAL_WEIGHTS["transaction"]
            + sig["location_overlaps"] * SIGNAL_WEIGHTS["location"]
            + sig["case_overlaps"] * SIGNAL_WEIGHTS["case"]
            + len(sig["shared_identifiers"]) * SIGNAL_WEIGHTS["shared_identifier"]
        )
        if weighted <= 0:
            continue
        n_sources = len(sig["sources"])
        independence = min(n_sources, MAX_INDEPENDENCE_SOURCES) * INDEPENDENCE_PER_SOURCE
        score = min(1.0, weighted / (weighted + SCORE_DENOMINATOR) + independence)
        relationships.append({
            "id": f"R{ida}-{idb}",
            "person_a": ida, "person_b": idb,
            "person_a_name": name_by_id.get(ida, ida),
            "person_b_name": name_by_id.get(idb, idb),
            "score": round(score, 3),
            "strength": _strength_from_score(score),
            "signals": {
                "calls": sig["calls"],
                "transactions": sig["transactions"],
                "location_overlaps": sig["location_overlaps"],
                "shared_identifiers": sig["shared_identifiers"],
                "case_overlaps": sig["case_overlaps"],
            },
            "sources": sorted(sig["sources"]),
            "dates": sorted({d for d in sig["dates"] if d}),
            "evidence": sig["evidence"],
            "n_sources": n_sources,
        })
    relationships.sort(key=lambda r: -r["score"])
    return relationships
