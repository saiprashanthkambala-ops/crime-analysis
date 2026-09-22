"""Case-scoped graph synchronization and graph read endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Person, User
from ..security import get_current_user
from ..services.graph_sync import sync_case_to_neo4j, reconcile_case_in_neo4j
from ..services.graph_view import get_case_graph
from ..services.neo4j_service import Neo4jConfigError, Neo4jConnectionError, run_read_query

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _authorized_case_ids(db: Session, user: User) -> list[str]:
    if user.role == "admin":
        from ..models import Case
        return [c.id for c in db.query(Case).all()]
    return [c.id for c in user.assigned_cases]


@router.get("")
def get_graph(
    case_ids: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the complete authorized graph for the requested/assigned cases."""
    requested = [x.strip() for x in (case_ids or "").split(",") if x.strip()]
    ids = requested or _authorized_case_ids(db, user)
    if requested:
        from ..security import ensure_case_access
        for cid in ids:
            ensure_case_access(db, user, cid)
    return get_case_graph(db, user, ids)


class GenerateGraphRequest(BaseModel):
    case_ids: list[str]


@router.post("/generate")
def generate_graph(
    body: GenerateGraphRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Synchronize and materialize the complete graph for selected cases."""
    from ..security import ensure_case_access

    ids = [x.strip() for x in body.case_ids if x and x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one case.")
    for cid in ids:
        ensure_case_access(db, user, cid)

    try:
        graph = get_case_graph(db, user, ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Graph generation failed. Check the backend log.") from exc

    if not graph.get("nodes"):
        raise HTTPException(
            status_code=422,
            detail="No graph nodes were generated for the selected case(s). Verify the case has imported entities and that Neo4j synchronization has completed.",
        )

    graph["generated"] = True
    graph["node_count"] = len(graph.get("nodes", []))
    graph["edge_count"] = len(graph.get("edges", []))
    return graph


@router.post("/sync/{case_id}")
def sync_graph(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..models import Case
    from ..security import ensure_case_access

    ensure_case_access(db, user, case_id)
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        result = sync_case_to_neo4j(db, case_id)
        return {"ok": True, "result": result, "verification": result.get("verification")}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (Neo4jConfigError, Neo4jConnectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/reconcile/{case_id}")
def reconcile_graph(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..security import ensure_case_access
    ensure_case_access(db, user, case_id)
    try:
        return reconcile_case_in_neo4j(db, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (Neo4jConfigError, Neo4jConnectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/sync-status/{case_id}")
def sync_status(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..models import Case
    from ..security import ensure_case_access
    ensure_case_access(db, user, case_id)
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return {
        "case_id": case.id,
        "status": case.neo4j_sync_status or "PENDING",
        "synced_at": case.neo4j_sync_at.isoformat() if case.neo4j_sync_at else None,
        "error": case.neo4j_sync_error,
        "counts": case.neo4j_sync_counts or {},
    }


@router.get("/cases/{case_id}")
def get_case_graph_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a complete Cytoscape-friendly graph for one case."""
    from ..security import ensure_case_access
    ensure_case_access(db, user, case_id)
    return get_case_graph(db, user, [case_id])


@router.get("/node-details")
def graph_node_details(
    node_id: str,
    node_type: str = "",
    case_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return authorized investigator-readable graph-node details with provenance."""
    from ..models import Case, Document, Entity, Event, Evidence, Person, person_entities
    from ..security import ensure_case_access

    if case_id:
        ensure_case_access(db, user, case_id)

    clean_type = (node_type or "").strip().lower()
    clean_id = (node_id or "").strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Graph node id is required.")

    def file_dict(doc):
        preview = (doc.source_text or "").strip()
        if len(preview) > 1800:
            preview = preview[:1800].rstrip() + "…"
        return {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "status": doc.status,
            "records_processed": doc.records_processed,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "source_preview": preview or None,
        }

    if clean_type in {"phone", "vehicle", "account", "location"}:
        prefix_map = {
            "phone": "PHONE",
            "vehicle": "VEHICLE",
            "account": "BANK_ACCOUNT",
            "location": "LOCATION",
        }
        entity_type = prefix_map[clean_type]
        normalized = clean_id.split(":", 1)[1] if ":" in clean_id else clean_id
        query = db.query(Entity).filter(
            Entity.entity_type == entity_type,
            Entity.normalized_value == normalized,
        )
        if case_id:
            query = query.filter(Entity.case_id == case_id)
        entities = query.order_by(Entity.id.asc()).all()
        if not entities:
            raise HTTPException(status_code=404, detail="Graph entity details not found.")

        entity_ids = [e.id for e in entities]
        source_ids = {e.source_document_id for e in entities if e.source_document_id}
        source_files = db.query(Document).filter(Document.id.in_(source_ids)).all() if source_ids else []
        source_by_id = {d.id: d for d in source_files}
        person_links = db.query(
            person_entities.c.person_id, person_entities.c.entity_id
        ).filter(person_entities.c.entity_id.in_(entity_ids)).all()
        person_ids = {row[0] for row in person_links if row[0]}
        people = db.query(Person).filter(Person.id.in_(person_ids)).all() if person_ids else []
        primary = entities[0]
        case_obj = db.get(Case, primary.case_id)

        return {
            "node_id": clean_id,
            "node_type": clean_type,
            "display_name": primary.original_value or primary.normalized_value,
            "entity_type": primary.entity_type,
            "value": primary.original_value or primary.normalized_value,
            "normalized_value": primary.normalized_value,
            "confidence": primary.confidence,
            "observed_at": " ".join(x for x in (primary.observed_date, primary.observed_time) if x) or None,
            "case": {"id": case_obj.id, "name": case_obj.name, "status": case_obj.status} if case_obj else None,
            "source_files": [file_dict(source_by_id[sid]) for sid in source_ids if sid in source_by_id],
            "related_people": [{"id": p.id, "name": p.name} for p in people],
        }

    if clean_type == "person":
        person = db.get(Person, clean_id)
        if not person:
            raise HTTPException(status_code=404, detail="Graph person details not found.")
        linked = (
            db.query(Entity)
            .join(person_entities, person_entities.c.entity_id == Entity.id)
            .filter(person_entities.c.person_id == person.id)
            .all()
        )
        if case_id:
            linked = [e for e in linked if e.case_id == case_id]
        source_ids = {e.source_document_id for e in linked if e.source_document_id}
        source_files = db.query(Document).filter(Document.id.in_(source_ids)).all() if source_ids else []
        case_obj = db.get(Case, case_id) if case_id else (db.get(Case, linked[0].case_id) if linked else None)
        return {
            "node_id": clean_id,
            "node_type": clean_type,
            "display_name": person.name or person.id,
            "entity_type": "PERSON",
            "value": person.name or person.id,
            "normalized_value": person.id,
            "case": {"id": case_obj.id, "name": case_obj.name, "status": case_obj.status} if case_obj else None,
            "source_files": [file_dict(d) for d in source_files],
            "related_people": [],
        }

    if clean_type in {"document", "event", "evidence", "case"}:
        if clean_type == "case":
            ensure_case_access(db, user, clean_id)
            obj = db.get(Case, clean_id)
        elif clean_type == "document":
            obj = db.get(Document, clean_id)
        elif clean_type == "event":
            obj = db.get(Event, int(clean_id)) if clean_id.isdigit() else None
        else:
            obj = db.get(Evidence, clean_id)
        if not obj:
            raise HTTPException(status_code=404, detail="Graph node details not found.")
        obj_case_id = getattr(obj, "case_id", None)
        if obj_case_id:
            ensure_case_access(db, user, obj_case_id)
        case_obj = db.get(Case, obj_case_id) if obj_case_id else None
        return {
            "node_id": clean_id,
            "node_type": clean_type,
            "display_name": getattr(obj, "filename", None) or getattr(obj, "event_type", None) or getattr(obj, "type", None) or clean_id,
            "entity_type": clean_type.upper(),
            "value": getattr(obj, "description", None) or getattr(obj, "source_reference", None) or getattr(obj, "filename", None) or clean_id,
            "case": {"id": case_obj.id, "name": case_obj.name, "status": case_obj.status} if case_obj else None,
            "source_files": [],
            "related_people": [],
        }

    raise HTTPException(status_code=400, detail="Unsupported graph node type.")

@router.get("/person/{person_id}/neighbors")
def person_neighbors(
    person_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    allowed_cases = _authorized_case_ids(db, user)
    query = """
    MATCH (p:Person {id: $person_id})-[r]-(n)
    WHERE $is_admin OR n.case_id IN $case_ids
    RETURN
      p.id AS person_id,
      p.name AS person_name,
      collect({
        id: coalesce(n.id, n.key),
        label: coalesce(n.name, n.value, n.filename, n.type, n.id, n.key),
        type: labels(n)[0],
        relationship: type(r),
        score: r.score,
        strength: r.strength
      }) AS neighbors
    """
    try:
        rows = run_read_query(
            query,
            {
                "person_id": person_id,
                "case_ids": allowed_cases,
                "is_admin": user.role == "admin",
            },
        )
    except (Neo4jConfigError, Neo4jConnectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Person is not present in Neo4j")
    return rows[0]
