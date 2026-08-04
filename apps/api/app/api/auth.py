"""Authentication endpoints: register, login, OTP, and current user."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

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


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbDep) -> TokenResponse:
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    user.last_login_at = utcnow()
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.post("/otp/request")
def request_otp(payload: OTPRequest, db: DbDep) -> dict:
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import User

    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    # Don't reveal whether the address exists.
    if user is not None:
        code = auth_service.issue_otp(db, user)
        db.commit()
        # Return the code in the response ONLY in local/dev so the flow is demoable
        # without an email channel. NEVER in any other environment: an attacker who
        # knows a victim's email could read the code and complete /otp/verify —
        # full pre-auth account takeover.
        if getattr(get_settings(), "environment", "local") == "local":
            return {"detail": "OTP issued", "dev_code": code}
    return {"detail": "OTP issued"}


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp(payload: OTPVerifyRequest, db: DbDep) -> TokenResponse:
    from sqlalchemy import select

    from app.models import User

    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if user is None or not auth_service.verify_user_otp(db, user, payload.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code"
        )
    db.commit()
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
