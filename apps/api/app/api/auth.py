"""Authentication endpoints: register, login, OTP, and current user."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import DbDep
from app.models import utcnow
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    OTPRequest,
    OTPVerifyRequest,
    RegisterRequest,
    TokenResponse,
    UpdateMeRequest,
    UserOut,
)
from app.security import CurrentUser, create_access_token, hash_password, verify_password
from app.services import audit, auth_service, rate_limit
from app.services.users import normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbDep) -> TokenResponse:
    user, _factory = auth_service.register_factory_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        factory_name_ar=payload.factory_name_ar,
        factory_name_en=payload.factory_name_en,
        locale=payload.locale,
    )
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role))


def _client_ip(request: Request) -> str:
    """Resolve the real client IP, honoring trusted reverse proxies.

    Behind a proxy (``TRUSTED_PROXY_COUNT`` > 0) the direct peer is the proxy, so
    ``request.client.host`` is the SAME for every user — collapsing the per-IP
    auth throttles into one global bucket (20 junk logins would lock everyone
    out). We instead read ``X-Forwarded-For`` and take the entry the outermost
    trusted proxy observed, counting ``trusted_proxy_count`` hops from the RIGHT.
    Counting from the right is spoof-resistant: a client can prepend fake entries,
    but the proxy always appends the address it actually saw, so those fakes are
    never selected. With 0 trusted proxies (local/CI) we trust only the peer.
    """
    from app.config import get_settings

    n = get_settings().trusted_proxy_count
    if n > 0:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if len(parts) >= n:
                return parts[-n]
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbDep) -> TokenResponse:
    email = normalize_email(payload.email)
    ip = _client_ip(request)
    # Blunt online password-spraying: cap per IP and per account separately so
    # neither one IP against many accounts nor many IPs against one account slips
    # through (CODE_AUDIT CRITICAL-1 / login throttle notes).
    rate_limit.check(f"login:ip:{ip}", limit=20, window_seconds=300)
    rate_limit.check(f"login:acct:{email}", limit=8, window_seconds=300)
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    user.last_login_at = utcnow()
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.post("/otp/request")
def request_otp(payload: OTPRequest, request: Request, db: DbDep) -> dict:
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import User

    email = normalize_email(payload.email)
    ip = _client_ip(request)
    rate_limit.check(f"otp_request:ip:{ip}", limit=15, window_seconds=300)
    rate_limit.check(f"otp_request:acct:{email}", limit=6, window_seconds=300)

    user = db.scalar(select(User).where(User.email == email))
    # Don't reveal whether the address exists.
    if user is not None:
        code = auth_service.issue_otp(db, user)
        db.commit()
        settings = get_settings()
        # Return the plaintext code ONLY in local env AND behind the explicit
        # SILK_DEV_EXPOSE_OTP flag. Anywhere else it's delivered out-of-band —
        # returning it would let anyone who knows an email complete /otp/verify.
        if getattr(settings, "environment", "local") == "local" and getattr(
            settings, "silk_dev_expose_otp", False
        ):
            return {"detail": "OTP issued", "dev_code": code}
    return {"detail": "OTP issued"}


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp(payload: OTPVerifyRequest, request: Request, db: DbDep) -> TokenResponse:
    from sqlalchemy import select

    from app.models import User

    email = normalize_email(payload.email)
    ip = _client_ip(request)
    rate_limit.check(f"otp_verify:ip:{ip}", limit=20, window_seconds=300)
    rate_limit.check(f"otp_verify:acct:{email}", limit=12, window_seconds=300)

    user = db.scalar(select(User).where(User.email == email))
    ok = user is not None and auth_service.verify_user_otp(db, user, payload.code)
    # Commit even on failure so the wrong-attempt counter persists across requests
    # (get_db never auto-commits) — otherwise the lockout would never trip.
    db.commit()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code"
        )
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.put("/me", response_model=UserOut)
def update_me(payload: UpdateMeRequest, db: DbDep, user: CurrentUser) -> UserOut:
    """Self-service profile edit (display name + UI locale)."""
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    return UserOut.model_validate(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordRequest, db: DbDep, user: CurrentUser) -> Response:
    """Change the signed-in user's password after re-verifying the current one.

    Rate-limited per account so a stolen session can't brute-force the current
    password, and audited (without ever recording either password).
    """
    rate_limit.check(f"change_password:{user.id}", limit=5, window_seconds=300)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    user.password_hash = hash_password(payload.new_password)
    audit.record(
        db,
        action="user.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor=user,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
