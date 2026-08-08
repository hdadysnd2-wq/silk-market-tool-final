"""Password hashing, JWT issuance, OTP handling, and role dependencies."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.logging import get_logger
from app.models import User, UserRole

log = get_logger(__name__)

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

# CSRF-unsafe (state-changing) HTTP methods. A cookie is an ambient credential
# the browser attaches automatically, so a cookie-authenticated request using one
# of these methods must additionally prove its Origin (below).
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_CSRF_ERROR = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Cross-origin request blocked",
)


def _enforce_same_origin(request: Request) -> None:
    """Reject a state-changing cookie-auth request whose Origin isn't allowlisted.

    Bearer-authenticated calls skip this — an attacker page cannot set the
    Authorization header cross-site, so ambient-credential CSRF doesn't apply. But
    the cookie is sent automatically, and ``POST /products`` accepts
    ``multipart/form-data`` (a CORS-"simple" type a cross-site form can submit with
    no preflight). Pinning the Origin/Referer to the trusted first-party origins
    closes that forged-request path. A browser sends ``Origin`` on every unsafe
    same-origin request, so a missing/foreign Origin (with no allowlisted Referer
    fallback) is treated as cross-site and blocked.

    The allowlist is ``settings.trusted_origins`` (CORS_ORIGINS ∪ APP_BASE_URL,
    loopback-equivalent in local) — not the raw CORS_ORIGINS — so a request from
    the app's own canonical web origin is never rejected just because the two
    variables drifted. A block is logged (origin + allowlist, no secrets) so the
    otherwise-opaque 403 is diagnosable.
    """
    allowed = set(get_settings().trusted_origins)
    # A wildcard only survives in local (the prod guard rejects it); there every
    # origin is trusted, matching the CORS middleware's own "*" behaviour.
    if "*" in allowed:
        return
    origin = request.headers.get("origin")
    if origin is not None:
        if origin not in allowed:
            _log_origin_block(request, origin, allowed)
            raise _CSRF_ERROR
        return
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc and f"{parts.scheme}://{parts.netloc}" in allowed:
            return
    _log_origin_block(request, origin, allowed)
    raise _CSRF_ERROR


def _log_origin_block(request: Request, origin: str | None, allowed: set[str]) -> None:
    """Record why a cookie-auth write was refused so the 403 isn't a black box.

    Origins are not secret, and this is exactly the pair an operator needs to see
    that (say) a custom web domain is missing from CORS_ORIGINS/APP_BASE_URL.
    """
    log.warning(
        "csrf_origin_blocked",
        method=request.method,
        path=request.url.path,
        origin=origin,
        referer=request.headers.get("referer"),
        allowed_origins=sorted(allowed),
    )


def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    # Prefer the Authorization: Bearer header (API clients, tests); fall back to
    # the httpOnly session cookie the browser sends on same-origin /api/v1 calls
    # (C2 — the token is never exposed to client JS).
    header_token = token
    token = header_token or request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _CREDENTIALS_ERROR
    # CSRF: only the cookie is ambient. When the request authenticated by cookie
    # (no explicit Bearer header) and mutates state, require an allowlisted Origin.
    if header_token is None and request.method in _UNSAFE_METHODS:
        _enforce_same_origin(request)
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
