"""Registration, login, and OTP flows."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models import Factory, User, UserRole, utcnow
from app.security import (
    generate_otp,
    hash_otp,
    hash_password,
    verify_otp,
    verify_password,
)
from app.services.users import create_user, normalize_email

log = get_logger(__name__)

# A pre-computed bcrypt hash of a random throwaway password. When authentication
# is attempted for an address with no account, we still run a full password
# verification against this dummy hash so the response time is indistinguishable
# from the wrong-password path — closing the account-enumeration timing oracle.
_DUMMY_PASSWORD_HASH = hash_password("timing-equalizer-not-a-real-password")


def register_factory_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str | None,
    factory_name_ar: str,
    factory_name_en: str,
    locale: str = "ar",
) -> tuple[User, Factory]:
    """Create a factory tenant and its first (owner) user."""
    email = normalize_email(email)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    factory = Factory(name_ar=factory_name_ar, name_en=factory_name_en)
    db.add(factory)
    db.flush()

    user = create_user(
        db,
        email=email,
        full_name=full_name,
        role=UserRole.factory_user,
        factory_id=factory.id,
        locale=locale,
        password_hash=hash_password(password),
    )
    log.info("factory_registered", user_id=str(user.id), factory_id=str(factory.id))
    return user, factory


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    # Always run a bcrypt verification, even when the user is missing, so the
    # miss path and the wrong-password path take the same time (no enumeration).
    password_ok = verify_password(password, user.password_hash if user else _DUMMY_PASSWORD_HASH)
    # A deactivated account is treated exactly like a bad credential — same 401,
    # same message — so login never reveals that the address exists but is
    # disabled (anti-enumeration; also what the admin deactivate flow relies on).
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    return user


def issue_otp(db: Session, user: User) -> str:
    """Generate a one-time code, store its hash, and return the plaintext.

    Locally the code is logged (no email vendor); the caller decides delivery.
    """
    code = generate_otp()
    ttl = get_settings().otp_ttl_minutes
    user.otp_code_hash = hash_otp(code)
    user.otp_expires_at = utcnow() + timedelta(minutes=ttl)
    user.otp_attempts = 0  # fresh code — reset the brute-force counter
    db.flush()
    # Never log the code — anyone with log access could complete /otp/verify.
    # The caller returns it out-of-band (and only in local env, per the API).
    log.info("otp_issued", user_id=str(user.id))
    return code


def verify_user_otp(db: Session, user: User, code: str) -> bool:
    """Verify a one-time code, counting wrong attempts and locking after the cap.

    The caller MUST commit afterwards even on a False result so the incremented
    attempt counter persists across requests — otherwise the lockout never trips.
    """
    # A deactivated account must not complete OTP either (parity with
    # ``authenticate``). get_current_user re-checks is_active on every request so
    # a token would grant no access regardless, but the passwordless path should
    # fail closed here too rather than mint a token for a disabled user.
    if not user.is_active:
        return False
    if user.otp_expires_at is None or user.otp_expires_at < utcnow():
        return False
    # Locked: too many wrong attempts against this code. Requires a fresh issue.
    if (user.otp_attempts or 0) >= get_settings().otp_max_attempts:
        return False
    if not verify_otp(code, user.otp_code_hash):
        user.otp_attempts = (user.otp_attempts or 0) + 1
        db.flush()
        return False
    # Single-use: clear on success.
    user.otp_code_hash = None
    user.otp_expires_at = None
    user.otp_attempts = 0
    user.last_login_at = utcnow()
    db.flush()
    return True
