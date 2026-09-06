"""Graph projection for the network visualization.

Builds nodes (Person, Phone, Vehicle, Bank Account, Location, Case,
Organization, Event) and edges (CALLED, TRANSFERRED_TO, ASSOCIATED_WITH,
LOCATED_AT, INVOLVED_IN, CONNECTED_TO) for Cytoscape.js.
"""


def build_graph(persons, events, entities, relationships):
    nodes = []
    edges = []
    seen_nodes = set()
    seen_edges = set()

    def add_node(nid, label, ntype, data=None):
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        nodes.append({"data": {"id": nid, "label": label, "type": ntype, **(data or {})}})

    def add_edge(sid, tid, label, etype):
        key = (sid, tid, label)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"data": {"id": f"{sid}-{tid}-{label}", "source": sid, "target": tid,
                                "label": label, "type": etype}})

    # person nodes
    for p in persons:
        add_node(p["id"], p["name"], "person", {"strength": None})

    # identifier nodes + edges to their owner
    for p in persons:
        ids = p.get("identifiers", {})
        for phone in ids.get("phone", []):
            nid = f"phone:{phone}"
            add_node(nid, phone, "phone")
            add_edge(p["id"], nid, "OWNS", "ASSOCIATED_WITH")
        for veh in ids.get("vehicle", []):
            nid = f"vehicle:{veh}"
            add_node(nid, veh, "vehicle")
            add_edge(p["id"], nid, "OWNS", "ASSOCIATED_WITH")
        for acc in ids.get("account", []):
            nid = f"account:{acc}"
            add_node(nid, acc, "account")
            add_edge(p["id"], nid, "OWNS", "ASSOCIATED_WITH")
        for loc in ids.get("location", []):
            nid = f"location:{loc}"
            add_node(nid, loc, "location")
            add_edge(p["id"], nid, "SEEN_AT", "LOCATED_AT")
        for case in p.get("cases", []):
            nid = f"case:{case}"
            add_node(nid, case, "case")
            add_edge(p["id"], nid, "INVOLVED_IN", "INVOLVED_IN")

    # event edges between persons
    for e in events:
        a, b = e.get("a_name"), e.get("b_name")
        if not a or not b:
            continue
        pa, pb = _person_id_for_name(persons, a), _person_id_for_name(persons, b)
        if not pa or not pb or pa == pb:
            continue
        label = "CALLED" if e.get("type") == "CALL" else "TRANSFERRED_TO" if e.get("type") == "TRANSACTION" else "CONNECTED_TO"
        add_edge(pa, pb, label, label)
        # attach the event as a node
        eid = f"event:{e.get('id')}"
        add_node(eid, e.get("description", "event")[:30], "event")
        add_edge(pa, eid, "ACTOR", "INVOLVED_IN")
        add_edge(eid, pb, "ACTOR", "INVOLVED_IN")

    # relationship edges (person-person)
    for r in relationships:
        add_edge(r["person_a"], r["person_b"], r["strength"], "CONNECTED_TO")

    return {"nodes": nodes, "edges": edges}


def _person_id_for_name(persons, name):
    from .normalization import normalize_name
    key = normalize_name(name)
    for p in persons:
        if normalize_name(p["name"]) == key:
            return p["id"]
    return None
