"""Create (or promote) the FIRST platform admin — the production bootstrap.

Demo accounts — including the demo admin — are deliberately local-only (C4:
well-known passwords must never exist on a public deployment), and the public
register flow only creates factory users. Without this command a fresh
production deployment has NO way to reach the admin console.

Run it once from a trusted operator shell (e.g. Railway's service shell):

    python -m app.seeds.create_admin owner@example.com --name "Owner"

Behaviour:
- The email does not exist → an active admin is created with a generated
  high-entropy password, printed ONCE to this terminal (never logged); change
  it after first login.
- The email exists → the user is promoted to admin (password unchanged).
- Idempotent: an existing active admin with that email is a no-op.

Every outcome writes an audit row (actor_label ``bootstrap:create_admin``).
"""

from __future__ import annotations

import argparse
import secrets

from app.db import session_scope
from app.models import User, UserRole
from app.security import hash_password
from app.services import audit


def create_or_promote_admin(
    db, email: str, full_name: str | None = None
) -> tuple[User, str | None]:
    """Return (user, generated_password_or_None). Caller commits."""
    normalized = email.lower().strip()
    if not normalized or "@" not in normalized:
        raise ValueError(f"Not a valid email address: {email!r}")

    user = db.query(User).filter(User.email == normalized).one_or_none()
    if user is not None:
        if user.role == UserRole.admin and user.is_active:
            return user, None  # already an active admin — nothing to do
        user.role = UserRole.admin
        # Staff are never tenant-scoped (same rule the admin console enforces).
        user.factory_id = None
        user.is_active = True
        audit.record(
            db,
            action="user.promoted_to_admin",
            entity_type="user",
            entity_id=user.id,
            actor_label="bootstrap:create_admin",
            payload={"email": normalized},
        )
        return user, None

    password = secrets.token_urlsafe(18)
    user = User(
        email=normalized,
        full_name=full_name,
        role=UserRole.admin,
        factory_id=None,
        locale="ar",
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor_label="bootstrap:create_admin",
        payload={"email": normalized, "role": UserRole.admin.value},
    )
    return user, password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote the first platform admin.")
    parser.add_argument("email", help="Admin email address")
    parser.add_argument("--name", default=None, help="Full name (optional)")
    args = parser.parse_args()

    with session_scope() as db:
        user, password = create_or_promote_admin(db, args.email, args.name)
        db.commit()
        if password is not None:
            # Printed ONCE to the operator's terminal on purpose; never logged.
            print(f"Admin created: {user.email}")
            print(f"One-time password (change it after first login): {password}")
        elif user.role == UserRole.admin:
            print(f"{user.email} is an active admin (created or promoted; password unchanged).")


if __name__ == "__main__":
    main()
