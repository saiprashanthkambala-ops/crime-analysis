"""Case-scoped Neo4j graph synchronization endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import ensure_case_access, get_current_user
from ..services.graph_sync import sync_case_to_neo4j
from ..services.neo4j_service import Neo4jConfigError, Neo4jConnectionError

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.post("/sync/{case_id}")
def sync_graph(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_case_access(db, user, case_id)
    try:
        return {"ok": True, "result": sync_case_to_neo4j(db, case_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Neo4jConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Neo4jConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
