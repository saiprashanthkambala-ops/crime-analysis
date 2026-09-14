"""Case-scoped graph synchronization and graph read endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Person, User
from ..security import get_current_user
from ..services.graph_sync import sync_case_to_neo4j
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
        return {"ok": True, "result": sync_case_to_neo4j(db, case_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (Neo4jConfigError, Neo4jConnectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
