"""Create (or promote) the FIRST platform admin — the production bootstrap.

Demo accounts — including the demo admin — are deliberately local-only (C4:
well-known passwords must never exist on a public deployment), and the public
register flow only creates factory users. Without this command a fresh
production deployment has NO way to reach the admin console.

Run it once from a shell inside the running API container (Railway starts
commands from the repo root, so the ``cd`` matters):

    cd /app/apps/api
    python -m app.seeds.create_admin owner@example.com --name "Owner"

The admin password is supplied by the operator — a hidden interactive prompt,
or ``SILK_BOOTSTRAP_ADMIN_PASSWORD`` for non-interactive shells. It is never
generated, printed, or logged.

Behaviour:
- The email does not exist -> an active admin is created with that password.
- The email is an existing active user -> promoted to admin: the supplied
  password replaces the old one (staff never keep a self-chosen factory
  credential) and any factory link is detached, with the previous role and
  factory recorded in the audit row.
- The email is already an active admin -> no-op; nothing is written.
- The email is a deactivated account -> refused. Deactivation is the
  platform's revocation mechanism; reactivate via the admin console instead.
"""

from __future__ import annotations

import argparse
import getpass
import os

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import User, UserRole
from app.security import hash_password
from app.services import audit
from app.services.users import create_user, normalize_email

# The console never accepts a staff password at all (unusable credential +
# OTP/reset flow), so there is no staff policy to reuse; require a floor above
# the register flow's min_length=8 for the credential that spans every tenant.
MIN_PASSWORD_LENGTH = 12

_email_validator: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


def create_or_promote_admin(
    db: Session, email: str, full_name: str | None = None, *, password: str
) -> tuple[User, str]:
    """Ensure ``email`` is an active admin; return (user, outcome).

    Outcome is ``"created"``, ``"promoted"``, or ``"noop"``. Caller commits.
    """
    normalized = normalize_email(email)
    try:
        _email_validator.validate_python(normalized)
    except ValidationError:
        raise ValueError(f"Not a valid email address: {email!r}") from None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Admin password must be at least {MIN_PASSWORD_LENGTH} characters")

    user = db.scalar(select(User).where(User.email == normalized))
    if user is not None:
        if not user.is_active:
            # Deactivation is the platform's credential revocation; a bootstrap
            # run must never silently undo it.
            raise ValueError(
                f"{normalized} is deactivated; reactivate it via the admin console first"
            )
        if user.role == UserRole.admin:
            return user, "noop"  # already an active admin — nothing to write
        previous_role = user.role
        previous_factory_id = user.factory_id
        user.role = UserRole.admin
        user.factory_id = None  # staff are never tenant-scoped
        # A promoted account must not keep its self-chosen factory password.
        user.password_hash = hash_password(password)
        audit.record(
            db,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            payload={
                "email": normalized,
                "role": UserRole.admin.value,
                "previous_role": previous_role.value,
                "previous_factory_id": str(previous_factory_id) if previous_factory_id else None,
                "password_rotated": True,
            },
        )
        return user, "promoted"

    user = create_user(
        db,
        email=normalized,
        full_name=full_name,
        role=UserRole.admin,
        factory_id=None,
        locale="ar",
        password_hash=hash_password(password),
    )
    return user, "created"


def _read_password() -> str:
    password = os.environ.get("SILK_BOOTSTRAP_ADMIN_PASSWORD")
    if password:
        return password
    password = getpass.getpass("New admin password (hidden, never stored in plaintext): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote the first platform admin.")
    parser.add_argument("email", help="Admin email address")
    parser.add_argument("--name", default=None, help="Full name (optional)")
    args = parser.parse_args()

    password = _read_password()
    try:
        # Printing inside the scope means a failed print rolls the work back,
        # so the command is always safely retryable.
        with session_scope() as db:
            user, outcome = create_or_promote_admin(db, args.email, args.name, password=password)
            if outcome == "created":
                print(f"Admin created: {user.email} (log in with the password you supplied).")
            elif outcome == "promoted":
                print(
                    f"{user.email} promoted to admin; the supplied password replaced the old"
                    " one and any factory link was detached (recorded in the audit log)."
                )
            else:
                print(f"{user.email} is already an active admin; nothing changed.")
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from None


if __name__ == "__main__":
    main()
