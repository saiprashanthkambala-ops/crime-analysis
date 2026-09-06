"""Entity resolution — cluster record mentions into canonical persons.

Clustering is conservative: two mentions are merged into the same person when
either (a) their normalized names are similar, or (b) they share a strong
identifier (phone / account / vehicle). Confidence and the evidence behind each
merge are retained so the system never *silently* merges identities.
"""
from difflib import SequenceMatcher

from .normalization import normalize_name, normalize_phone, normalize_vehicle, normalize_account


def name_similarity(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    pa, pb = na.split(), nb.split()
    if pa[0] == pb[0]:
        # same first name; stronger when one side is a single-token variant
        # (e.g. "Suresh" vs "Suresh Reddy", "Ravi K." vs "Ravi Kumar")
        if len(pa) == 1 or len(pb) == 1:
            return 0.9
        if len(pa) >= 2 and len(pb) >= 2 and pa[1][0] == pb[1][0]:
            return 0.9
        return 0.8
    return SequenceMatcher(None, na, nb).ratio()


def _shared(ids_a, ids_b):
    sa = {normalize_phone(x) or normalize_vehicle(x) or normalize_account(x) for x in ids_a if x}
    sb = {normalize_phone(x) or normalize_vehicle(x) or normalize_account(x) for x in ids_b if x}
    return sa & sb


def resolve_mentions(mentions):
    """Group raw mentions into clusters representing distinct real-world people.

    Returns a list of dicts:
        { "name": canonical display name, "mentions": [...], "confidence": ...,
          "signals": [...] }
    """
    clusters = []  # list of dicts

    for m in mentions:
        ids_m = (
            m.get("identifiers", {}).get("phone", [])
            + m.get("identifiers", {}).get("account", [])
            + m.get("identifiers", {}).get("vehicle", [])
        )
        best = None
        best_score = 0.0
        for c in clusters:
            sim = name_similarity(m.get("name", ""), c["name"])
            shared = _shared(ids_m, c["all_identifiers"])
            score = sim
            if shared:
                score = max(score, 0.95)
            if score > best_score:
                best_score = score
                best = c
        if best is not None and best_score >= 0.8:
            best["mentions"].append(m)
            best["all_identifiers"] += ids_m
            if best_score == 0.95:
                best["signals"].add("shared identifier")
            else:
                best["signals"].add("name similarity")
        else:
            clusters.append({
                "name": m.get("name", "Unknown"),
                "mentions": [m],
                "all_identifiers": list(ids_m),
                "signals": set(),
            })

    results = []
    for c in clusters:
        # canonical name = most common display name
        names = [m.get("name") for m in c["mentions"] if m.get("name")]
        canonical = max(set(names), key=names.count) if names else "Unknown"
        results.append({
            "name": canonical,
            "mentions": c["mentions"],
            "identifiers": {
                "phone": sorted({normalize_phone(p) for m in c["mentions"]
                                 for p in m.get("identifiers", {}).get("phone", []) if p}),
                "vehicle": sorted({normalize_vehicle(v) for m in c["mentions"]
                                   for v in m.get("identifiers", {}).get("vehicle", []) if v}),
                "account": sorted({normalize_account(a) for m in c["mentions"]
                                   for a in m.get("identifiers", {}).get("account", []) if a}),
                "location": sorted({l for m in c["mentions"]
                                    for l in m.get("identifiers", {}).get("location", []) if l}),
            },
            "confidence": 0.95 if c["signals"] & {"shared identifier"} else 0.8,
            "signals": sorted(c["signals"]),
        })
    return results


def compute_resolution_candidates(mentions):
    """Return pairwise candidate same-person resolutions with confidence + signals."""
    candidates = []
    for i in range(len(mentions)):
        for j in range(i + 1, len(mentions)):
            a, b = mentions[i], mentions[j]
            sim = name_similarity(a.get("name", ""), b.get("name", ""))
            ida = (a.get("identifiers", {}).get("phone", [])
                   + a.get("identifiers", {}).get("account", [])
                   + a.get("identifiers", {}).get("vehicle", []))
            idb = (b.get("identifiers", {}).get("phone", [])
                   + b.get("identifiers", {}).get("account", [])
                   + b.get("identifiers", {}).get("vehicle", []))
            shared = _shared(ida, idb)
            signals = []
            if shared:
                signals.append("shared identifier")
            if sim >= 0.8:
                signals.append("name similarity")
            if not signals:
                continue
            confidence = "HIGH" if shared else ("MEDIUM" if sim >= 0.9 else "LOW")
            candidates.append({
                "record_a": a.get("name"),
                "record_b": b.get("name"),
                "signals": signals,
                "confidence": confidence,
            })
    return candidates
