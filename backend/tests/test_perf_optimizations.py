import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fastapi import HTTPException
from app.config import settings
from app.database import Base
from app.models import Case, Document, Entity, Event, Evidence, Relationship, User
from app.security import ensure_case_access_batch
from app.services.case_analysis import (
    build_case_analysis,
    build_llm_context,
    get_cached_case_analysis,
    set_cached_case_analysis,
    invalidate_case_analysis_cache,
    _case_context_cache,
)


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    user_a = User(id=1, username="alice", password_hash="hash", role="investigator")
    user_b = User(id=2, username="bob", password_hash="hash", role="investigator")
    admin = User(id=3, username="admin", password_hash="hash", role="admin")
    session.add_all([user_a, user_b, admin])
    session.flush()

    case1 = Case(id="case-1", name="Case 1", status="open", created_by=1)
    case2 = Case(id="case-2", name="Case 2", status="open", created_by=1)
    case3 = Case(id="case-3", name="Case 3", status="open", created_by=2)
    case1.users.append(user_a)
    case2.users.append(user_a)
    case3.users.append(user_b)
    session.add_all([case1, case2, case3])

    entity1 = Entity(
        id=1,
        case_id="case-1",
        entity_type="PERSON",
        normalized_value="john doe",
        original_value="John Doe",
    )
    event1 = Event(
        id=1,
        case_id="case-1",
        event_type="CALL",
        description="Call between parties",
        observed_date="2026-01-01",
    )
    evidence1 = Evidence(
        id="ev-1",
        case_id="case-1",
        type="call_association",
        confidence=0.9,
    )
    rel1 = Relationship(
        id="rel-1",
        person_a_id="P-A",
        person_b_id="P-B",
        score=0.85,
        strength="HIGH",
    )
    session.add_all([entity1, event1, evidence1, rel1])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_db_pool_configuration():
    assert hasattr(settings, "DB_POOL_SIZE")
    assert hasattr(settings, "DB_MAX_OVERFLOW")
    assert hasattr(settings, "DB_POOL_TIMEOUT")
    assert hasattr(settings, "DB_POOL_RECYCLE")
    assert settings.DB_POOL_SIZE >= 5


def test_ensure_case_access_batch(test_db):
    user_a = test_db.query(User).filter_by(username="alice").first()
    user_b = test_db.query(User).filter_by(username="bob").first()
    admin = test_db.query(User).filter_by(username="admin").first()

    # User A has access to case-1 and case-2
    ensure_case_access_batch(test_db, user_a, ["case-1", "case-2"])

    # Admin has access to all cases
    ensure_case_access_batch(test_db, admin, ["case-1", "case-2", "case-3"])

    # User A does NOT have access to case-3 (owned by User B)
    with pytest.raises(HTTPException) as exc_info:
        ensure_case_access_batch(test_db, user_a, ["case-1", "case-3"])
    assert exc_info.value.status_code == 403

    # Non-existent case raises 404
    with pytest.raises(HTTPException) as exc_info:
        ensure_case_access_batch(test_db, user_a, ["case-1", "case-999"])
    assert exc_info.value.status_code == 404


def test_case_analysis_caching_and_invalidation(test_db):
    user_a = test_db.query(User).filter_by(username="alice").first()

    # Clear cache before test
    invalidate_case_analysis_cache()

    # 1. First build (Cache Miss)
    t0 = time.perf_counter()
    ctx1 = build_case_analysis(test_db, user_a, ["case-1"])
    t_miss = time.perf_counter() - t0

    assert ctx1["cases"][0]["id"] == "case-1"
    assert len(ctx1["entities"]) >= 1

    # 2. Second build (Cache Hit)
    t1 = time.perf_counter()
    ctx2 = build_case_analysis(test_db, user_a, ["case-1"])
    t_hit = time.perf_counter() - t1

    assert ctx2["cases"][0]["id"] == "case-1"
    # Cache hit should be practically instantaneous (< 10ms)
    assert t_hit < 0.05

    # 3. Test build_llm_context memoization
    prompt1 = build_llm_context(ctx2)
    prompt2 = build_llm_context(ctx2)
    assert prompt1 == prompt2
    assert "_llm_compact" in ctx2

    # 4. Invalidation by case ID
    invalidate_case_analysis_cache("case-1")
    assert get_cached_case_analysis("case-1") is None


def test_cache_authorization_safety(test_db):
    user_a = test_db.query(User).filter_by(username="alice").first()
    user_b = test_db.query(User).filter_by(username="bob").first()

    invalidate_case_analysis_cache()

    # User A analyzes case-1 (cached)
    build_case_analysis(test_db, user_a, ["case-1"])

    # User B tries to build analysis on case-1 -> must be denied despite cache existing
    with pytest.raises(HTTPException) as exc_info:
        build_case_analysis(test_db, user_b, ["case-1"])
    assert exc_info.value.status_code == 403


def test_chat_cache_key_and_llm_messages():
    from app.routers.analysis import _chat_cache_key, _llm_messages
    import json

    context = {
        "case_ids": ["case-1"],
        "cases": [{"id": "case-1", "name": "Case 1"}],
        "entities": [],
        "events": [],
        "evidence": [],
        "relationships": [],
        "counts": {"people": 0, "entities": 0, "relationships": 0, "evidence": 0},
    }

    key_without_analysis = _chat_cache_key(context, "Who is suspect?", [])
    key_with_analysis = _chat_cache_key(context, "Who is suspect?", [], generated_analysis="Analysis summary")

    assert key_without_analysis != key_with_analysis

    msgs = _llm_messages(
        context,
        "System prompt",
        "Who is suspect?",
        [],
        {"tool": "none", "status": "ok", "observations": [], "note": "none"},
        generated_analysis="Key suspect is John Doe",
    )
    user_msg_content = json.loads(msgs[-1]["content"])
    assert "generated_case_analysis" in user_msg_content
    assert user_msg_content["generated_case_analysis"] == "Key suspect is John Doe"


