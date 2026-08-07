"""Test fixtures: an isolated database, an API client, and factory/email helpers.

The suite runs against a dedicated ``silk_test`` database (override with
``TEST_DATABASE_URL``). Schema is created once from the models; each test runs in
its own transaction-wrapped session that is rolled back afterwards, so tests are
independent. Celery is unused here — services and the send path are called
directly, which is exactly how the production send task invokes them.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://silk:silk@127.0.0.1:5432/silk_test")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("COMTRADE_OFFLINE", "1")
os.environ.setdefault("MOCK_EMIT_ENGAGEMENT", "0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long-000")

# Run Celery tasks inline (eager) during tests so ``.delay()`` executes the task
# synchronously in-process — no broker needed. This MUST be set before anything
# imports ``app.workers.celery_app`` (which reads it at import time), i.e. before
# the ``app.main`` import below pulls in the routers that enqueue tasks. A route
# commits its entity before ``.delay()``, so the eager task's own session sees it;
# after the eager task commits, a subsequent ``GET`` (new session) sees the result.
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ["CELERY_TASK_EAGER_PROPAGATES"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Buyer,
    BuyerSource,
    Campaign,
    Contact,
    Email,
    EmailStatus,
    Factory,
    Market,
    Product,
    User,
    UserRole,
    VerificationStatus,
    utcnow,
)
from app.security import create_access_token, hash_password  # noqa: E402


def _alembic_config():
    """Alembic config with absolute paths — independent of pytest's cwd."""
    from pathlib import Path

    from alembic.config import Config

    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    # The schema comes from `alembic upgrade head` — the SAME path production
    # start-api.sh runs — not from Base.metadata.create_all. create_all silently
    # masked model↔migration drift (and forced a hand-copied duplicate of the
    # audit-log triggers here; migration 0013 is now their single source).
    from alembic import command

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    command.upgrade(_alembic_config(), "head")
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def db(_schema):
    session = SessionLocal()
    # Clean slate per test. audit_log is append-only AND now rejects TRUNCATE
    # (the C6 BEFORE TRUNCATE trigger), so it can no longer be reset "through the
    # hole" (TRUNCATE silently skipping the row-level DELETE trigger). Explicitly
    # disable its immutability triggers for the reset, TRUNCATE every table, then
    # re-enable — the bypass is visible and scoped to test teardown, not a gap in
    # the production guard.
    table_names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # The rate limiter keys on the (constant) TestClient IP, so its buckets
    # (Redis-backed with an in-process fallback) would otherwise accumulate
    # across tests and spuriously 429; the session-revocation denylist likewise
    # leaks jtis across tests. Clear both before each test for isolation.
    from app.services import rate_limit, sessions

    rate_limit.reset()
    sessions.reset()
    yield


@pytest.fixture
def client(db):
    return TestClient(app)


# -- data builders ---------------------------------------------------------


@pytest.fixture
def market(db) -> Market:
    m = Market(
        iso2="IN",
        name_en="India",
        name_ar="الهند",
        region="South Asia",
        currency="INR",
        primary_language="hi",
    )
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def eu_market(db) -> Market:
    m = Market(
        iso2="DE",
        name_en="Germany",
        name_ar="ألمانيا",
        region="Europe",
        currency="EUR",
        primary_language="en",
        is_eu=True,
    )
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def factory(db) -> Factory:
    f = Factory(
        name_ar="مصنع اختبار",
        name_en="Test Factory",
        sector="plastics",
        city="Jeddah",
        contact_person="Owner",
        contact_email="owner@testfactory-export.com",
        postal_address="Jeddah, Saudi Arabia",
        sending_domain="testfactory-export.com",
        spf_ok=True,
        dkim_ok=True,
        dmarc_ok=True,
        warmup_started_at=utcnow(),
        warmup_day=14,
    )
    db.add(f)
    db.commit()
    return f


@pytest.fixture
def factory_user(db, factory) -> User:
    u = User(
        email="user@testfactory.com",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.factory_user,
        factory_id=factory.id,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def admin_user(db) -> User:
    u = User(
        email="admin@silk.test",
        password_hash=hash_password("Passw0rd!"),
        role=UserRole.admin,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def auth_headers(factory_user) -> dict:
    token = create_access_token(factory_user.id, factory_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hs_code(db):
    from app.models import HSCode

    code = db.get(HSCode, "392010")
    if code is None:
        code = HSCode(
            code="392010",
            level=6,
            parent_code="3920",
            description_en="Film of ethylene polymers",
            description_ar="أغشية من بوليمرات الإيثيلين",
            sector="plastics",
        )
        db.add(code)
        db.commit()
    return code


@pytest.fixture
def product(db, factory, hs_code) -> Product:
    p = Product(
        factory_id=factory.id,
        name_ar="فيلم",
        name_en="Stretch Film",
        description_en="Polyethylene film",
        hs_code="392010",
        hs_confirmed_by_user=True,
        classification_status="classified",
        currency="USD",
        price_min=1200,
        price_max=1600,
    )
    db.add(p)
    db.commit()
    return p


def make_buyer_with_contact(
    db, market_iso2: str = "IN", email: str = "buyer@acme.example.in"
) -> tuple[Buyer, Contact]:
    if db.get(Market, market_iso2) is None:
        db.add(
            Market(
                iso2=market_iso2,
                name_en=market_iso2,
                name_ar=market_iso2,
                region="test",
                currency="USD",
                primary_language="en",
            )
        )
        db.flush()
    buyer = Buyer(
        name="Acme Importers",
        normalized_name="acme importers",
        country_iso2=market_iso2,
        source=BuyerSource.customs,
        source_confidence=0.85,
        employee_count=120,
    )
    db.add(buyer)
    db.flush()
    contact = Contact(
        buyer_id=buyer.id,
        email=email,
        full_name="Jane Buyer",
        title="Procurement",
        language="en",
        verification_status=VerificationStatus.valid,
    )
    db.add(contact)
    db.commit()
    return buyer, contact


def make_campaign(db, factory, product, market_iso2="IN") -> Campaign:
    c = Campaign(
        factory_id=factory.id,
        product_id=product.id,
        market_iso2=market_iso2,
        name="Test Campaign",
    )
    db.add(c)
    db.commit()
    return c


def make_draft_email(db, campaign, buyer, contact, language="en") -> Email:
    e = Email(
        campaign_id=campaign.id,
        contact_id=contact.id,
        buyer_id=buyer.id,
        status=EmailStatus.draft,
        subject="Hello",
        body_text="Body",
        language=language,
        unsubscribe_token=uuid.uuid4().hex,
    )
    db.add(e)
    db.commit()
    return e
