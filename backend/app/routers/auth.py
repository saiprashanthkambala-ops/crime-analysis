from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from collections import defaultdict, deque
from threading import Lock
import time

from ..config import settings

from ..database import get_db
from ..models import User
from ..security import create_access_token, verify_password, get_current_user, log_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()


def _rate_limit_keys(request: Request, username: str) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}", f"user:{username.strip().lower()}"


def _check_login_rate_limit(request: Request, username: str) -> None:
    now = time.monotonic()
    cutoff = now - settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    keys = _rate_limit_keys(request, username)
    with _rate_limit_lock:
        for key in keys:
            attempts = _failed_logins[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
                raise HTTPException(429, "Too many failed login attempts. Please try again later.")


def _record_failed_login(request: Request, username: str) -> None:
    now = time.monotonic()
    keys = _rate_limit_keys(request, username)
    with _rate_limit_lock:
        for key in keys:
            attempts = _failed_logins[key]
            attempts.append(now)


def _clear_login_failures(request: Request, username: str) -> None:
    with _rate_limit_lock:
        for key in _rate_limit_keys(request, username):
            _failed_logins.pop(key, None)


class LoginBody(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(response: Response, request: Request, body: LoginBody, db: Session = Depends(get_db)):
    _check_login_rate_limit(request, body.username)
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        _record_failed_login(request, body.username)
        raise HTTPException(401, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    _clear_login_failures(request, body.username)
    log_audit(db, user.id, "login")
    token = create_access_token(user)
    response.set_cookie(
        key="crime_analysis_session",
        value=token,
        httponly=True,
        secure=settings.APP_ENV.lower() in {"production", "prod"},
        samesite="lax",
        path="/",
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
    )
    return LoginResponse(user=user.as_dict())


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user.as_dict()


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_audit(db, user.id, "logout")
    response.delete_cookie(
        key="crime_analysis_session",
        path="/",
        secure=settings.APP_ENV.lower() in {"production", "prod"},
        samesite="lax",
    )
    return {"ok": True}
