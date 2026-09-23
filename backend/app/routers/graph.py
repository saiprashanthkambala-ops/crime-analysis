"""Case-scoped graph synchronization and graph read endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Person, User
from ..security import get_current_user, ensure_case_access
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
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..models import Case
    from ..security import ensure_case_access

    ensure_case_access(db, user, case_id)
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        result = sync_case_to_neo4j(db, case_id, force=force)
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
    raw_counts = case.neo4j_sync_counts or {}
    clean_counts = {k: v for k, v in raw_counts.items() if not k.startswith("_")} if isinstance(raw_counts, dict) else {}
    return {
        "case_id": case.id,
        "status": case.neo4j_sync_status or "PENDING",
        "synced_at": case.neo4j_sync_at.isoformat() if case.neo4j_sync_at else None,
        "error": case.neo4j_sync_error,
        "counts": clean_counts,
        "fingerprint": raw_counts.get("_fingerprint") if isinstance(raw_counts, dict) else None,
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


@router.get("/entity")
def entity_details(
    node_id: str,
    case_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return case-scoped entity details and provenance for graph-node inspection."""
    from ..models import Case, Document, Entity, Event, Evidence, Person, person_entities

    requested_case_ids = [case_id] if case_id else []
    if case_id:
        ensure_case_access(db, user, case_id)

    entity = None
    raw_id = node_id.split(':', 1)[1] if ':' in node_id else node_id
    try:
        if raw_id.isdigit():
            entity = db.get(Entity, int(raw_id))
    except (TypeError, ValueError):
        entity = None

    if entity is None:
        candidates = db.query(Entity)
        if requested_case_ids:
            candidates = candidates.filter(Entity.case_id.in_(requested_case_ids))
        prefix = node_id.split(':', 1)[0].upper() if ':' in node_id else ''
        type_map = {"PHONE": "PHONE", "VEHICLE": "VEHICLE", "ACCOUNT": "BANK_ACCOUNT", "LOCATION": "LOCATION"}
        entity_type = type_map.get(prefix)
        if entity_type:
            candidates = candidates.filter(Entity.entity_type == entity_type)
        entity = candidates.filter(
            (Entity.normalized_value == raw_id) | (Entity.original_value == raw_id)
        ).order_by(Entity.id.asc()).first()

    if entity is None:
        raise HTTPException(status_code=404, detail="Entity details not found for this graph node.")

    ensure_case_access(db, user, entity.case_id)
    case = db.get(Case, entity.case_id) if entity.case_id else None
    document = db.get(Document, entity.source_document_id) if entity.source_document_id else None

    linked_people = (
        db.query(Person)
        .join(person_entities, person_entities.c.person_id == Person.id)
        .filter(person_entities.c.entity_id == entity.id)
        .all()
    )

    return {
        "entity": {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "original_value": entity.original_value,
            "normalized_value": entity.normalized_value,
            "confidence": entity.confidence,
            "extraction_method": entity.extraction_method,
            "source_reference": entity.source_reference,
            "source_document_id": entity.source_document_id,
            "observed_date": entity.observed_date,
            "observed_time": entity.observed_time,
            "date_precision": entity.date_precision,
            "meta": entity.meta or {},
        },
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description or "",
            "status": case.status,
        } if case else None,
        "document": {
            "id": document.id,
            "filename": document.filename,
            "file_type": document.file_type,
            "status": document.status,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "processed_at": document.processed_at.isoformat() if document.processed_at else None,
            "file_size": document.file_size or 0,
            "source_available": bool(document.source_text or document.filename),
        } if document else None,
        "people": [{"id": p.id, "name": p.name} for p in linked_people],
    }
