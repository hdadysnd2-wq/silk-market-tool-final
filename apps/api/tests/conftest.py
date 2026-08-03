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


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # The audit-log immutability trigger lives in the migration, not the models;
    # recreate it here so trigger-dependent tests exercise the real behaviour.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log"))
        conn.execute(
            text(
                """
                CREATE TRIGGER audit_log_no_update_delete
                BEFORE UPDATE OR DELETE ON audit_log
                FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
                """
            )
        )
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(_schema):
    session = SessionLocal()
    # Clean slate per test. TRUNCATE (unlike DELETE) does not fire the row-level
    # BEFORE-DELETE trigger that makes audit_log append-only, so it can reset
    # every table including the ledger.
    table_names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


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
