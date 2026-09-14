"""Case analysis workspace and evidence-grounded NVIDIA chat."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, log_audit
from ..services.case_analysis import build_case_analysis, _case_ids
from ..services.nvidia_client import chat as nvidia_chat, is_configured

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    case_ids: list[str] = Field(default_factory=list)


def _context_for_chat(db: Session, user: User, requested: list[str]) -> dict:
    return build_case_analysis(db, user, requested or None)


@router.get("")
def get_analysis(
    case_ids: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested = [x.strip() for x in (case_ids or "").split(",") if x.strip()]
    context = build_case_analysis(db, user, requested or None)
    log_audit(db, user.id, "view_analysis", "case", ",".join(context["case_ids"]))
    return context


@router.post("/generate")
def generate_analysis(
    body: AnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_case_analysis(db, user, body.case_ids or None)
    if not is_configured():
        raise HTTPException(status_code=503, detail="NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")
    system = (
        "You are the Crime Analysis investigation assistant. "
        "Use ONLY the supplied case context. Summarize observable facts, "
        "relationships, evidence, and existing relationship-strength signals. "
        "Do not invent facts, dates, people, evidence, or scores. "
        "Do not claim guilt or innocence. Relationship scores are evidence-strength "
        "signals, not probabilities of guilt. Clearly separate facts from interpretation."
    )
    user_msg = "Generate an investigator-facing analysis of the selected case(s).\n\n" + json.dumps(context, default=str)
    try:
        result = nvidia_chat([{"role": "system", "content": system}, {"role": "user", "content": user_msg}], stream=False)
        content = result.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NVIDIA analysis request failed: {exc}") from exc
    log_audit(db, user.id, "generate_analysis", "case", ",".join(context["case_ids"]))
    return {"analysis": content, "context": context}


@router.post("/chat")
def chat_endpoint(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = _context_for_chat(db, user, body.case_ids)
    if not is_configured():
        raise HTTPException(status_code=503, detail="NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")
    system = (
        "You are an evidence-grounded investigation assistant. "
        "Answer only from the supplied case context. Explain relationship signals "
        "and graph facts clearly. Do not fabricate. Never state that a person is "
        "a confirmed criminal or that a graph score is probability of guilt. "
        "When evidence is insufficient, say so. Keep answers useful to an investigator."
    )
    payload = (
        "Authorized case context:\n"
        + json.dumps(context, default=str)
        + "\n\nInvestigator question:\n"
        + body.message
    )
    try:
        result = nvidia_chat([{"role": "system", "content": system}, {"role": "user", "content": payload}], stream=False)
        answer = result.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NVIDIA chat request failed: {exc}") from exc
    log_audit(db, user.id, "analysis_chat", "case", ",".join(context["case_ids"]))
    return {"answer": answer, "context": context}
