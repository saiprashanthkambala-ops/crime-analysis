"""Case analysis workspace and evidence-grounded NVIDIA chat."""

import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, log_audit
from ..services.case_analysis import build_case_analysis, build_llm_context
from ..services.graph_view import get_case_graph
from ..services.investigation_agent import run_investigation_tools
from ..services.nvidia_client import (
    NVIDIAClientError,
    chat as nvidia_chat,
    get_cached_stream,
    is_configured,
    set_cached_stream,
    stream_chat,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    case_ids: list[str] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=8)


def _llm_messages(
    context: dict,
    task: str,
    question: str | None = None,
    history: list[dict[str, str]] | None = None,
    tool_result: dict | None = None,
):
    system = (
        "You are the Crime Analysis investigation assistant. "
        "Use ONLY the supplied case data. Do not invent facts, dates, people, "
        "evidence, relationships, or scores. Relationship scores are evidence-strength "
        "signals, not probabilities of guilt. Do not declare a person guilty or innocent. "
        "Clearly distinguish observed facts from interpretation. "
        "Return clean Markdown with headings and bullet lists when appropriate."
    )
    payload = {
        "task": task,
        "case_data": build_llm_context(context),
    }
    if question:
        payload["investigator_question"] = question
    if tool_result:
        payload["deterministic_tool_observations"] = {
            "tool_name": tool_result.get("tool"),
            "status": tool_result.get("status"),
            "observations": tool_result.get("observations"),
            "note": tool_result.get("note"),
        }
    messages = [{"role": "system", "content": system}]
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = item.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": str(content)[:3000]})
    messages.append({"role": "user", "content": json.dumps(payload, default=str, ensure_ascii=False)})
    return messages


def _chat_cache_key(context: dict, message: str, history: list[dict[str, str]] | None) -> str:
    payload = {
        "case_ids": context.get("case_ids", []),
        "context": build_llm_context(context),
        "question": re.sub(r"\s+", " ", message.strip().lower()),
        "history": [
            {"role": h.get("role"), "content": str(h.get("content", ""))[:1200]}
            for h in (history or [])[-2:]
        ],
    }
    raw = json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_stream_response(answer: str, context: dict, tool: str | None = None):
    def event_stream():
        for i in range(0, len(answer), 120):
            yield json.dumps({"type": "token", "content": answer[i:i + 120]}, ensure_ascii=False, separators=(",", ":")) + "\n"
        yield json.dumps({
            "type": "done", "context": context, "tool": tool,
            "tool_status": "cached", "mode": "cache",
        }, default=str, separators=(",", ":")) + "\n"
    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _is_greeting(message: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", message.lower())
    return normalized in {
        "hi", "hii", "hiii", "hello", "hey", "heyy", "yo",
        "goodmorning", "goodevening",
    }


def _fast_answer(context: dict, message: str) -> str | None:
    """Answer simple factual questions without an LLM round-trip."""
    q = re.sub(r"[^a-z0-9 ]", " ", message.lower()).strip()
    q = re.sub(r"\s+", " ", q)

    counts = context.get("counts", {})
    rels = context.get("relationships", [])

    if any(x in q for x in ("how many people", "number of people", "people in this case")):
        return f"There are {counts.get('people', 0)} people represented in the selected case data."
    if any(x in q for x in ("how many relationships", "number of relationships")):
        return f"There are {counts.get('relationships', 0)} relationship records in the selected case data."
    if any(x in q for x in ("how many entities", "number of entities")):
        return f"There are {counts.get('entities', 0)} extracted entities in the selected case data."
    if any(x in q for x in ("how many evidence", "number of evidence")):
        return f"There are {counts.get('evidence', 0)} evidence records in the selected case data."

    if any(x in q for x in ("strongest relationship", "highest relationship score", "highest score")) and rels:
        strongest = max(rels, key=lambda r: (r.get("score") or 0))
        a = strongest.get("person_a", {}).get("name") or strongest.get("person_a", {}).get("id")
        b = strongest.get("person_b", {}).get("name") or strongest.get("person_b", {}).get("id")
        return (
            f"**Strongest recorded relationship:** {a} ↔ {b}\n\n"
            f"- Score: {strongest.get('score', '—')}\n"
            f"- Strength: {strongest.get('strength', '—')}\n"
            f"- Decision: {strongest.get('decision') or 'Not recorded'}"
        )

    if any(x in q for x in ("most connected", "highest degree", "most connections")) and rels:
        degrees = {}
        names = {}
        for r in rels:
            for side in ("person_a", "person_b"):
                person = r.get(side) or {}
                pid = person.get("id")
                if pid:
                    degrees[pid] = degrees.get(pid, 0) + 1
                    names[pid] = person.get("name") or pid
        if degrees:
            pid = max(degrees, key=degrees.get)
            return f"**Most connected in the recorded relationship set:** {names[pid]} with {degrees[pid]} relationship links."

    return None


@router.get("")
def get_analysis(case_ids: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requested = [x.strip() for x in (case_ids or "").split(",") if x.strip()]
    context = build_case_analysis(db, user, requested or None)
    graph = get_case_graph(db, user, requested or None)
    context.update(graph)
    log_audit(db, user.id, "view_analysis", "case", ",".join(context["case_ids"]))
    return context


@router.get("/graph")
def get_analysis_graph(case_ids: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requested = [x.strip() for x in (case_ids or "").split(",") if x.strip()]
    return get_case_graph(db, user, requested or None)


@router.get("/nvidia-status")
def nvidia_status(user: User = Depends(get_current_user)):
    return {
        "configured": is_configured(),
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "message": "NVIDIA API key is configured on the backend."
        if is_configured()
        else "NVIDIA API key is missing from the backend environment.",
    }


@router.get("/nvidia-ping")
def nvidia_ping(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not is_configured():
        raise HTTPException(status_code=503, detail="NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")
    try:
        result = nvidia_chat([{"role": "user", "content": "Reply with exactly: NVIDIA_OK"}])
        content = result.choices[0].message.content or ""
        log_audit(db, user.id, "nvidia_ping", "system", None)
        return {"ok": True, "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "response": content}
    except NVIDIAClientError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=502, detail="NVIDIA provider test failed. Check backend logs.")


@router.post("/generate")
def generate_analysis(body: AnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    context = build_case_analysis(db, user, body.case_ids or None)
    if not is_configured():
        raise HTTPException(status_code=503, detail="NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")

    def event_stream():
        try:
            for token in stream_chat(
                _llm_messages(
                    context,
                    "Generate a concise investigator-facing analysis of the selected case(s). "
                    "Highlight important relationships, entity patterns, evidence, and notable observations.",
                )
            ):
                yield json.dumps({"type": "token", "content": token}, ensure_ascii=False, separators=(",", ":")) + "\n"
            log_audit(db, user.id, "generate_analysis", "case", ",".join(context["case_ids"]))
            yield json.dumps(
                {"type": "done", "context": context, "mode": "streaming"},
                default=str,
                separators=(",", ":"),
            ) + "\n"
        except NVIDIAClientError as exc:
            yield json.dumps({"type": "error", "detail": str(exc)}, separators=(",", ":")) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "detail": "NVIDIA analysis streaming request failed. Check backend logs."}, separators=(",", ":")) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/suspicious")
def suspicious_relationships(
    case_ids: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested = [x.strip() for x in (case_ids or "").split(",") if x.strip()]
    context = build_case_analysis(db, user, requested or None)
    candidates = sorted(
        context.get("relationships", []),
        key=lambda r: (r.get("score") or 0),
        reverse=True,
    )[:25]
    return {
        "case_ids": context["case_ids"],
        "method": "relationship_score",
        "candidates": candidates,
        "note": "Candidates prioritize recorded relationship strength. They are not findings of guilt.",
    }


@router.post("/chat")
def chat_endpoint(body: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    context = build_case_analysis(db, user, body.case_ids or None)
    if not is_configured():
        raise HTTPException(status_code=503, detail="NVIDIA API is not configured. Set NVIDIA_API_KEY on the backend.")

    if _is_greeting(body.message):
        answer = (
            "Hello. I’m ready to analyze the selected case data. "
            "Ask me about relationships, evidence, entities, network structure, "
            "or suspicious connection candidates."
        )
        log_audit(db, user.id, "analysis_chat", "case", ",".join(context["case_ids"]))
        return {"answer": answer, "context": context, "mode": "deterministic"}

    fast_answer = _fast_answer(context, body.message)
    if fast_answer:
        log_audit(db, user.id, "analysis_chat_fast_path", "case", ",".join(context["case_ids"]))
        return {"answer": fast_answer, "context": context, "mode": "deterministic"}

    # Fast cache lookup is performed after the deterministic tool decision so
    # cache entries remain tied to the actual tool path and selected-case context.
    cache_key = _chat_cache_key(context, body.message, body.history)
    cached_answer = get_cached_stream(cache_key)
    if cached_answer is not None:
        log_audit(db, user.id, "analysis_chat_cache_hit", "case", ",".join(context["case_ids"]))
        return _cached_stream_response(cached_answer, context)

    tool_result = run_investigation_tools(db, user, context["case_ids"], body.message, context)
    tool_observations = tool_result.get("observations")
    messages = _llm_messages(
        context,
        "Answer the investigator's question using ONLY the supplied case data and deterministic tool observations. Be concise and evidence-grounded. Do not invent values.",
        body.message,
        body.history[-4:] if body.history else [],
        tool_result,
    )

    def event_stream():
        chunks: list[str] = []
        try:
            for token in stream_chat(messages):
                chunks.append(token)
                yield json.dumps({"type": "token", "content": token}, ensure_ascii=False, separators=(",", ":")) + "\n"
            answer = "".join(chunks)
            set_cached_stream(cache_key, answer)
            log_audit(db, user.id, "analysis_chat", "case", ",".join(context["case_ids"]))
            yield json.dumps(
                {
                    "type": "done",
                    "context": context,
                    "tool": tool_result.get("tool"),
                    "tool_status": tool_result.get("status"),
                    "mode": "streaming",
                },
                default=str,
                separators=(",", ":"),
            ) + "\n"
        except NVIDIAClientError as exc:
            yield json.dumps({"type": "error", "detail": str(exc)}, separators=(",", ":")) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "detail": "NVIDIA streaming request failed. Check backend logs."}, separators=(",", ":")) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
