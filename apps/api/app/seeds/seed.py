"""Idempotent seed script.

Loads reference data (HS codes, markets), demo users (a factory owner, an admin,
an analyst), six Saudi factories across both pilot sectors, and one product per
factory. Running it twice is safe: every insert is guarded by an existence check.

    python -m app.seeds.seed
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import session_scope
from app.logging import get_logger
from app.models import (
    Factory,
    HSCode,
    Market,
    Product,
    User,
    UserRole,
    WorldTrade,
    utcnow,
)
from app.providers.registry import get_embedding_provider
from app.security import hash_password
from app.seeds.reference import HS_CODES, MARKETS
from app.services import hs_classifier

log = get_logger(__name__)

DEMO_PASSWORD = "Demo1234!"

# (name_en, name_ar, sector, city, product_name_en, product_name_ar, desc_en, hs, price)
FACTORIES: list[dict] = [
    {
        "name_en": "Jeddah Poly Industries",
        "name_ar": "صناعات جدة للبلاستيك",
        "sector": "plastics",
        "city": "Jeddah",
        "product_en": "HDPE Stretch Film",
        "product_ar": "أغشية تغليف متمددة",
        "desc_en": "Industrial polyethylene stretch film for pallet wrapping and packaging.",
        "hs": "392010",
        "price": (1200, 1600),
    },
    {
        "name_en": "Riyadh Pipe Works",
        "name_ar": "مصنع الرياض للأنابيب",
        "sector": "plastics",
        "city": "Riyadh",
        "product_en": "Rigid PVC Water Pipe",
        "product_ar": "أنابيب مياه صلبة",
        "desc_en": "Rigid PVC pipe for potable water networks, various diameters.",
        "hs": "391723",
        "price": (800, 1400),
    },
    {
        "name_en": "Dammam Packaging Co",
        "name_ar": "شركة الدمام للتعبئة",
        "sector": "plastics",
        "city": "Dammam",
        "product_en": "Polyethylene Shopping Bags",
        "product_ar": "أكياس تسوق بولي إيثيلين",
        "desc_en": "Printed polyethylene sacks and bags for retail and wholesale.",
        "hs": "392321",
        "price": (900, 1500),
    },
    {
        "name_en": "Al-Madinah Dates Factory",
        "name_ar": "مصنع المدينة للتمور",
        "sector": "food",
        "city": "Madinah",
        "product_en": "Premium Ajwa Dates",
        "product_ar": "تمور عجوة فاخرة",
        "desc_en": "Sorted and packed Ajwa and Sukkary dates, export-grade dried fruit.",
        "hs": "080410",
        "price": (3000, 6000),
    },
    {
        "name_en": "Qassim Sweets Manufacturing",
        "name_ar": "مصنع القصيم للحلويات",
        "sector": "food",
        "city": "Buraydah",
        "product_en": "Date-filled Confectionery",
        "product_ar": "حلويات محشوة بالتمر",
        "desc_en": "Sugar confectionery and toffee with date paste, no cocoa.",
        "hs": "170490",
        "price": (2000, 3500),
    },
    {
        "name_en": "Jeddah Juice Company",
        "name_ar": "شركة جدة للعصائر",
        "sector": "food",
        "city": "Jeddah",
        "product_en": "Pomegranate Fruit Juice",
        "product_ar": "عصير رمان",
        "desc_en": "Single-fruit pomegranate juice concentrate and nectar for export.",
        "hs": "200980",
        "price": (1500, 2600),
    },
]

DEMO_USERS = [
    {"email": "admin@demo.silk", "role": UserRole.admin, "name": "Platform Admin"},
    {"email": "analyst@demo.silk", "role": UserRole.analyst, "name": "Internal Analyst"},
]


def seed_reference(db) -> None:
    for code, level, parent, en, ar, sector in HS_CODES:
        if db.get(HSCode, code) is None:
            db.add(
                HSCode(
                    code=code,
                    level=level,
                    parent_code=parent,
                    description_en=en,
                    description_ar=ar,
                    sector=sector,
                )
            )
    for iso2, en, ar, region, currency, lang, gcc, eu, us in MARKETS:
        if db.get(Market, iso2) is None:
            db.add(
                Market(
                    iso2=iso2,
                    name_en=en,
                    name_ar=ar,
                    region=region,
                    currency=currency,
                    primary_language=lang,
                    is_gcc=gcc,
                    is_eu=eu,
                    is_us=us,
                )
            )
    db.flush()


def seed_users_and_factories(db) -> None:
    embedder = get_embedding_provider()

    for spec in DEMO_USERS:
        if db.scalar(select(User).where(User.email == spec["email"])) is None:
            db.add(
                User(
                    email=spec["email"],
                    password_hash=hash_password(DEMO_PASSWORD),
                    full_name=spec["name"],
                    role=spec["role"],
                    locale="ar",
                )
            )

    for idx, spec in enumerate(FACTORIES):
        owner_email = f"factory{idx + 1}@demo.silk"
        if db.scalar(select(User).where(User.email == owner_email)) is not None:
            continue

        factory = Factory(
            name_en=spec["name_en"],
            name_ar=spec["name_ar"],
            description_en=f"Saudi manufacturer of {spec['product_en'].lower()}.",
            description_ar=f"مصنع سعودي لإنتاج {spec['product_ar']}.",
            sector=spec["sector"],
            city=spec["city"],
            country_iso2="SA",
            contact_person="Export Manager",
            contact_email=f"export@{_domain(spec['name_en'])}",
            contact_phone="+966 12 000 0000",
            postal_address=f"{spec['city']} Industrial City, Saudi Arabia",
            sending_domain=f"{_domain(spec['name_en'])}",
            # First factory ships-ready for the demo; the rest need DNS setup.
            spf_ok=idx == 0,
            dkim_ok=idx == 0,
            dmarc_ok=idx == 0,
            warmup_started_at=utcnow() if idx == 0 else None,
            warmup_day=14 if idx == 0 else 0,
            onboarding_completed=True,
        )
        db.add(factory)
        db.flush()

        db.add(
            User(
                email=owner_email,
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=f"{spec['name_en']} Owner",
                role=UserRole.factory_user,
                factory_id=factory.id,
                locale="ar",
            )
        )

        product = Product(
            factory_id=factory.id,
            name_en=spec["product_en"],
            name_ar=spec["product_ar"],
            description_en=spec["desc_en"],
            description_ar=spec["desc_en"],
            price_min=spec["price"][0],
            price_max=spec["price"][1],
            currency="USD",
        )
        db.add(product)
        db.flush()

        hs_classifier.classify_product(db, product)
        # Classification only proposes (I2); confirm the intended demo HS code so
        # discovery can run straight away. The code is a seeded catalogue entry.
        hs_classifier.confirm_hs_code(db, product, spec["hs"], None)
        product.embedding = embedder.embed([f"{product.name_en} {product.description_en}"])[0]

    db.flush()


def _domain(name_en: str) -> str:
    slug = "".join(ch for ch in name_en.lower() if ch.isalnum() or ch == " ")
    return "-".join(slug.split()[:3]) + "-export.com"


# --- world-trade demo data (funnel Stage 1) ------------------------------
# Transit hubs carry inflated import volumes (re-exports) so the demo shows the
# guard (I9) demoting them below genuine markets. HS6 codes match the demo
# products so `make demo` renders a populated "world screened → top 5".
_TRANSIT_HUBS = {"ARE", "NLD", "SGP", "HKG", "BEL"}
_DEMO_HS6 = ["392010", "391723", "392321", "080410", "170490", "200980"]
#: (importer_iso3, base import in USD millions). Hubs are deliberately high raw.
_WORLD_IMPORTERS = [
    ("USA", 78.0),
    ("DEU", 52.0),
    ("GBR", 41.0),
    ("IND", 60.0),
    ("FRA", 33.0),
    ("ESP", 22.0),
    ("BRA", 18.0),
    ("EGY", 9.0),
    ("SAU", 7.0),
    ("ARE", 95.0),  # transit hub — inflated
    ("NLD", 88.0),  # transit hub
    ("SGP", 70.0),  # transit hub
    ("HKG", 64.0),  # transit hub
    ("BEL", 40.0),  # transit hub
]


def seed_world_trade(db, base_year: int = 2023) -> None:
    """Populate the ``world_trade`` Stage-1 table for the demo HS6 codes.

    Idempotent: skipped if any rows already exist. Values are deterministic (no
    randomness) so the funnel ranking is reproducible in the demo and tests.
    """
    if db.scalar(select(func.count()).select_from(WorldTrade)):
        return
    for hs6 in _DEMO_HS6:
        salt = int(hs6[-2:])  # vary volumes per code, deterministically
        for iso3, base_m in _WORLD_IMPORTERS:
            latest = (base_m + salt) * 1_000_000.0
            prev = latest * 0.9  # ~+11% YoY
            db.add(
                WorldTrade(
                    hs6=hs6,
                    importer_iso3=iso3,
                    year=base_year,
                    import_usd=latest,
                    yoy_growth=round((latest - prev) / prev, 4),
                    cagr_3y=round(((latest / prev) ** (1 / 3)) - 1, 4),
                    is_transit_hub=iso3 in _TRANSIT_HUBS,
                    is_mirror=False,
                    source="UN Comtrade (demo seed)",
                )
            )
    db.flush()
    log.info("seed_world_trade", codes=len(_DEMO_HS6), importers=len(_WORLD_IMPORTERS))


def run() -> dict:
    with session_scope() as db:
        seed_reference(db)
        seed_users_and_factories(db)
        seed_world_trade(db)
        counts = {
            "hs_codes": db.scalar(select(func.count()).select_from(HSCode)),
            "markets": db.scalar(select(func.count()).select_from(Market)),
            "users": db.scalar(select(func.count()).select_from(User)),
            "factories": db.scalar(select(func.count()).select_from(Factory)),
            "products": db.scalar(select(func.count()).select_from(Product)),
            "world_trade": db.scalar(select(func.count()).select_from(WorldTrade)),
        }
    log.info("seed_complete", **counts)
    return counts


if __name__ == "__main__":
    result = run()
    print("Seed complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print(f"\nDemo login password for all accounts: {DEMO_PASSWORD}")
    print("  factory1@demo.silk … factory6@demo.silk (factory users)")
    print("  admin@demo.silk, analyst@demo.silk (internal team)")
