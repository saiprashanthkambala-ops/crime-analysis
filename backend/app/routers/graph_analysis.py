"""Deterministic graph-analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user
from ..services.graph_analysis import GraphAnalysisUnavailable, analyze_cases, analyze_case, multi_hop_for_person, shortest_path_for_people

router = APIRouter(prefix="/api/graph-analysis", tags=["graph-analysis"])


@router.get("")
def selected_cases_analysis(
    case_ids: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ids = [x.strip() for x in case_ids.split(",") if x.strip()]
    try:
        return analyze_cases(db, user, ids)
    except GraphAnalysisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{case_id}")
def case_analysis(
    case_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return analyze_case(db, user, case_id)
    except GraphAnalysisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{case_id}/multi-hop")
def multi_hop(
    case_id: str,
    person_id: str,
    max_hops: int = Query(default=3, ge=1, le=5),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return multi_hop_for_person(db, user, case_id, person_id, max_hops)
    except GraphAnalysisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{case_id}/shortest-path")
def shortest_path(
    case_id: str,
    source_person_id: str,
    target_person_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return shortest_path_for_people(db, user, case_id, source_person_id, target_person_id)
    except GraphAnalysisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
