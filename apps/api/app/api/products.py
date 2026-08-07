"""Product upload, HS classification, and confirmation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product, resolve_factory
from app.models import HSCode, Product
from app.models.product import Product as ProductModel
from app.schemas.product import HSCodeOut, HSConfirmRequest, ProductAccepted, ProductOut
from app.security import CurrentUser
from app.services import engine, hs_classifier, rate_limit
from app.services.storage import get_storage, new_image_key
from app.workers.tasks import process_product_intake

router = APIRouter(tags=["products"])

# Product images are small photos; cap the upload so a client can't exhaust
# worker memory by streaming a multi-GB body into an in-memory read.
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# C19 (partial) — both product intake and manual re-classify trigger a paid
# Anthropic vision call. Rate-limit the intake fan-out per user so it can't be
# looped to run unbounded paid classifications. (A vision reservation + cache is
# a documented follow-up; only the endpoint rate limit lands here.)
PRODUCT_INTAKE_RATE_LIMIT = 30  # intake / re-classify runs per user per hour
PRODUCT_INTAKE_WINDOW_SECONDS = 3600

# Never store an image under a client-declared active-content type (text/html,
# image/svg+xml): served from the storage origin it would be stored-XSS. Keep a
# recognised raster type as declared; store anything else as octet-stream.
_SAFE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _coerce_optional_price(value: str | None, field: str) -> float | None:
    """Coerce an optional numeric multipart field.

    Browsers submit empty ``<input>`` values as ``""`` rather than omitting the
    field, so declaring these as ``float`` makes FastAPI 422 on a blank price.
    We take them as strings instead: blank (or whitespace) means "unset" → None,
    anything else must parse as a float, and genuine garbage is a clean 400.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be a number or left blank",
        ) from None


# A sync `def` route runs in Starlette's threadpool, so its blocking DB commit
# and boto3 upload never stall the single event loop (audit H2 / H1). It was
# `async def` doing sync work inline — two concurrent uploads against a slow S3
# froze every poll request. Read the upload synchronously off `image.file`.
@router.post("/products", response_model=ProductAccepted, status_code=status.HTTP_202_ACCEPTED)
def create_product(
    db: DbDep,
    user: CurrentUser,
    name_ar: str = Form(...),
    name_en: str = Form(...),
    description_ar: str | None = Form(None),
    description_en: str | None = Form(None),
    price_min: str | None = Form(None),
    price_max: str | None = Form(None),
    cost_per_unit: str | None = Form(None),
    currency: str = Form("USD"),
    classify: bool = Form(True),
    image: UploadFile | None = File(None),
) -> ProductAccepted:
    # C19 — intake runs a paid vision classification; rate-limit per user.
    rate_limit.check(
        f"product_intake:{user.id}",
        limit=PRODUCT_INTAKE_RATE_LIMIT,
        window_seconds=PRODUCT_INTAKE_WINDOW_SECONDS,
    )
    factory = resolve_factory(db, user)

    price_min_val = _coerce_optional_price(price_min, "price_min")
    price_max_val = _coerce_optional_price(price_max, "price_max")
    cost_per_unit_val = _coerce_optional_price(cost_per_unit, "cost_per_unit")

    image_url = None
    image_key = None
    if image is not None:
        # Bounded read: pull at most MAX+1 bytes so an oversized upload is rejected
        # without buffering the whole body. Read off the underlying spooled file
        # (sync) so the handler stays a threadpool `def`, not an event-loop `async`.
        data = image.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Image too large (max 10 MB)",
            )
        storage = get_storage()
        key = new_image_key(image.filename or "product.jpg")
        ctype = (
            image.content_type
            if image.content_type in _SAFE_IMAGE_TYPES
            else "application/octet-stream"
        )
        image_url = storage.put(key, data, ctype)
        image_key = key  # the worker fetches bytes by this key, not the URL

    product = Product(
        factory_id=factory.id,
        name_ar=name_ar,
        name_en=name_en,
        description_ar=description_ar,
        description_en=description_en,
        image_url=image_url,
        image_key=image_key,
        price_min=price_min_val,
        price_max=price_max_val,
        cost_per_unit=cost_per_unit_val,
        currency=currency,
        classification_status="pending",
    )
    db.add(product)
    # Commit FIRST so the (eager or real) worker task can load the row in its own
    # session, then enqueue the intake pipeline (vision → HS proposal → embedding).
    db.commit()

    # Snapshot the *pending* product for the 202 body BEFORE enqueuing: under eager
    # mode the task runs in-process during .delay() and would otherwise bleed the
    # classified result into this accepted response. The client polls GET for it.
    accepted = ProductOut.model_validate(product)
    accepted.classification_status = "pending"
    task = process_product_intake.delay(str(product.id), deepen=False)
    return ProductAccepted(task_id=task.id, product=accepted)


@router.get("/products", response_model=list[ProductOut])
def list_products(db: DbDep, user: CurrentUser) -> list[ProductOut]:
    factory = resolve_factory(db, user)
    rows = db.scalars(
        select(Product).where(Product.factory_id == factory.id).order_by(Product.created_at.desc())
    ).all()
    return [ProductOut.model_validate(p) for p in rows]


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product: ProductModel = Depends(get_owned_product)) -> ProductOut:
    return ProductOut.model_validate(product)


@router.post(
    "/products/{product_id}/classify",
    response_model=ProductAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def classify(
    user: CurrentUser,
    product: ProductModel = Depends(get_owned_product),
) -> ProductAccepted:
    """Re-run the intake pipeline (vision → HS proposal → embedding) in the worker.

    Returns 202 immediately; the client polls ``GET /products/{id}`` for the
    refreshed classification once the task finishes.
    """
    # C19 — the re-classify path triggers the same paid vision call as intake;
    # share the per-user intake rate limit.
    rate_limit.check(
        f"product_intake:{user.id}",
        limit=PRODUCT_INTAKE_RATE_LIMIT,
        window_seconds=PRODUCT_INTAKE_WINDOW_SECONDS,
    )
    accepted = ProductOut.model_validate(product)
    task = process_product_intake.delay(str(product.id), deepen=False)
    return ProductAccepted(task_id=task.id, product=accepted)


@router.put("/products/{product_id}/hs-code", response_model=ProductOut)
def confirm_hs(
    payload: HSConfirmRequest,
    db: DbDep,
    user: CurrentUser,
    product: ProductModel = Depends(get_owned_product),
) -> ProductOut:
    """Confirm the product's HS6 (the single writer of ``hs_code``, invariant I2).

    Accepts any structurally valid HS6 — not only the small seeded catalogue — so
    the manual-entry fallback works when the classifier failed to propose a match.
    A code absent from the local catalogue is backfilled from the engine's WCO
    reference (official description, real sourced data), then confirmed.
    """
    if db.get(HSCode, payload.hs_code) is None:
        is_valid, description = engine.hs6_reference(payload.hs_code)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid HS6 code {payload.hs_code}",
            )
        db.add(
            HSCode(
                code=payload.hs_code,
                level=6,
                parent_code=payload.hs_code[:4],
                description_en=description or f"HS {payload.hs_code}",
                description_ar=description or f"رمز {payload.hs_code}",
            )
        )
        db.flush()
    hs_classifier.confirm_hs_code(db, product, payload.hs_code, user.id)
    db.commit()
    return ProductOut.model_validate(product)


@router.get("/hs-codes/search", response_model=list[HSCodeOut])
def search_hs_codes(q: str, db: DbDep, user: CurrentUser, limit: int = 20) -> list[HSCodeOut]:
    pattern = f"%{q}%"
    rows = db.scalars(
        select(HSCode)
        .where(
            (HSCode.description_en.ilike(pattern))
            | (HSCode.description_ar.ilike(pattern))
            | (HSCode.code.like(f"{q}%"))
        )
        .where(HSCode.level == 6)
        .limit(limit)
    ).all()
    return [HSCodeOut.model_validate(r) for r in rows]
