"""Password hashing, JWT issuance, OTP handling, and role dependencies."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserRole

_ALGO = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# -- passwords -------------------------------------------------------------


def _bcrypt_hash(raw: str) -> str:
    # bcrypt operates on at most 72 bytes; truncate so long inputs still hash.
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def _bcrypt_verify(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def hash_password(raw: str) -> str:
    return _bcrypt_hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _bcrypt_verify(raw, hashed)


# -- OTP -------------------------------------------------------------------


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return _bcrypt_hash(code)


def verify_otp(code: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return _bcrypt_verify(code, hashed)


# -- JWT -------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, role: UserRole) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        # Unique token id — the handle server-side revocation (logout) keys on.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[_ALGO])


# -- dependencies ----------------------------------------------------------

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


SESSION_COOKIE = "silk_token"


def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    # Prefer the Authorization: Bearer header (API clients, tests); fall back to
    # the httpOnly session cookie the browser sends on same-origin /api/v1 calls
    # (C2 — the token is never exposed to client JS).
    token = token or request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_ERROR from exc

    # Server-side revocation: a logged-out jti is dead even though the JWT
    # still verifies. Tokens minted before the jti claim existed skip this
    # (their 12h TTL bounds the exposure); is_revoked fails open on a Redis
    # blip — the is_active check below stays the hard kill switch.
    from app.services import sessions

    if sessions.is_revoked(payload.get("jti")):
        raise _CREDENTIALS_ERROR

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Dependency factory enforcing that the caller holds one of ``roles``."""

    def _dep(user: CurrentUser) -> User:
        if roles and user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    return _dep


def require_staff(user: CurrentUser) -> User:
    """Admin or analyst — the internal concierge team."""
    if user.role not in (UserRole.admin, UserRole.analyst):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only")
    return user


def assert_factory_access(user: User, factory_id: uuid.UUID) -> None:
    """A factory user may only touch their own tenant; staff may touch any."""
    if user.role in (UserRole.admin, UserRole.analyst):
        return
    if user.factory_id != factory_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your factory")
