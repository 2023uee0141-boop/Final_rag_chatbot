from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from mongo_store import (
    create_user,
    find_user,
    set_user_password_hash,
    upsert_env_admin,
    get_users_collection,
)


ALGORITHM: str = "HS256"
PWD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
TEST_USERNAME = "test"
TEST_PASSWORD = "test1234"

USERS_FILE = Path(os.getenv("USERS_FILE", "users.json"))
_USERS_LOCK = threading.Lock()
_LOCAL_USERS_MIGRATED = False


def _mongo_enabled() -> bool:
    return get_users_collection() is not None


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _get_secret_key() -> str:
    # For local/dev convenience we allow a default; for real deployments set AUTH_SECRET_KEY.
    return _env("AUTH_SECRET_KEY", "dev-secret-change-me") or "dev-secret-change-me"


def _get_access_token_exp_minutes() -> int:
    raw = _env("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    try:
        minutes = int(raw or "120")
        return max(1, minutes)
    except Exception:
        return 120


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class User(BaseModel):
    username: str


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=256)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _get_configured_username() -> str:
    return _normalize_username(_env("AUTH_USERNAME", "admin") or "admin")


def _normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()

def _load_users() -> dict[str, str]:
    if not USERS_FILE.exists():
        return {}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {_normalize_username(str(k)): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_users(users: dict[str, str]) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _save_local_user(username: str, password_hash: str) -> None:
    users = _load_users()
    users[_normalize_username(username)] = password_hash
    _save_users(users)


def _ensure_env_admin(users: dict[str, str]) -> dict[str, str]:
    """If AUTH_PASSWORD is configured, ensure AUTH_USERNAME exists in users.json.

    This keeps backward compatibility with the old env-only auth.
    """
    username = _get_configured_username()
    password = _env("AUTH_PASSWORD")
    if not password:
        return users
    password_hash = PWD_CONTEXT.hash(password)
    if _mongo_enabled():
        upsert_env_admin(username, password_hash)
        return users
    if username in users:
        return users
    users = dict(users)
    users[username] = password_hash
    return users


def _ensure_test_user(users: dict[str, str]) -> dict[str, str]:
    password_hash = PWD_CONTEXT.hash(TEST_PASSWORD)
    if _mongo_enabled():
        set_user_password_hash(TEST_USERNAME, password_hash)
        return users
    users = dict(users)
    users[TEST_USERNAME] = password_hash
    return users


def _migrate_local_users_to_mongo() -> None:
    global _LOCAL_USERS_MIGRATED
    if _LOCAL_USERS_MIGRATED or not _mongo_enabled():
        return
    for username, password_hash in _load_users().items():
        username = _normalize_username(username)
        if username:
            create_user(username, password_hash)
    _LOCAL_USERS_MIGRATED = True


def _authenticate(username: str, password: str) -> Optional[User]:
    username = _normalize_username(username)
    if not username:
        return None

    with _USERS_LOCK:
        if _mongo_enabled():
            _ensure_env_admin({})
            _ensure_test_user({})
            _migrate_local_users_to_mongo()
            record = find_user(username)
            stored_hash = record.get("password_hash") if record else None
            local_hash = _load_users().get(username)
        else:
            existing = _load_users()
            users = _ensure_env_admin(existing)
            users = _ensure_test_user(users)
            if users != existing:
                _save_users(users)
            stored_hash = users.get(username)
            local_hash = None

    if not stored_hash and not local_hash:
        return None

    password = password or ""
    verified_hash = None
    if stored_hash:
        try:
            if PWD_CONTEXT.verify(password, stored_hash):
                verified_hash = stored_hash
        except Exception:
            verified_hash = None

    if verified_hash is None and local_hash:
        try:
            if PWD_CONTEXT.verify(password, local_hash):
                verified_hash = local_hash
        except Exception:
            verified_hash = None

    if verified_hash is None:
        return None

    if _mongo_enabled() and verified_hash == local_hash and local_hash != stored_hash:
        set_user_password_hash(username, local_hash)

    return User(username=username)


def _create_access_token(subject: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    to_encode = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": expire,
    }
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


@auth_router.post("/signup")
def signup(req: SignupRequest) -> dict[str, str]:
    username = _normalize_username(req.username)
    if not username:
        raise HTTPException(status_code=400, detail="Username required")

    password_hash = PWD_CONTEXT.hash(req.password)
    with _USERS_LOCK:
        users = _ensure_env_admin(_load_users())
        users = _ensure_test_user(users)
        if _mongo_enabled():
            _ensure_env_admin({})
            _ensure_test_user({})
            _migrate_local_users_to_mongo()
            if find_user(username) or username in users:
                raise HTTPException(status_code=400, detail="Username already exists")
            if not create_user(username, password_hash):
                raise HTTPException(status_code=400, detail="Username already exists")
            _save_local_user(username, password_hash)
        else:
            if username in users:
                raise HTTPException(status_code=400, detail="Username already exists")
            users[username] = password_hash
            _save_users(users)

    return {"status": "ok"}


@auth_router.post("/token", response_model=TokenResponse)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    user = _authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_access_token(
        subject=user.username,
        expires_minutes=_get_access_token_exp_minutes(),
    )
    return TokenResponse(access_token=token)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            raise credentials_exception
        return User(username=username)
    except JWTError:
        raise credentials_exception


@auth_router.get("/me", response_model=User)
def read_users_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
