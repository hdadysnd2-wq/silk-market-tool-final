"""Product upload, HS classification, and confirmation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DbDep, get_owned_product, resolve_factory
from app.models import HSCode, Product
from app.models.product import Product as ProductModel
from app.providers.registry import get_embedding_provider, get_llm_provider
from app.schemas.product import HSCodeOut, HSConfirmRequest, ProductOut
from app.security import CurrentUser
from app.services import hs_classifier, product_vision
from app.services.storage import get_storage, new_image_key

router = APIRouter(tags=["products"])


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    db: DbDep,
    user: CurrentUser,
    name_ar: str = Form(...),
    name_en: str = Form(...),
    description_ar: str | None = Form(None),
    description_en: str | None = Form(None),
    price_min: float | None = Form(None),
    price_max: float | None = Form(None),
    cost_per_unit: float | None = Form(None),
    currency: str = Form("USD"),
    classify: bool = Form(True),
    image: UploadFile | None = File(None),
) -> ProductOut:
    factory = resolve_factory(db, user)

    image_url = None
    if image is not None:
        data = await image.read()
        storage = get_storage()
        key = new_image_key(image.filename or "product.jpg")
        image_url = storage.put(key, data, image.content_type or "image/jpeg")

    product = Product(
        factory_id=factory.id,
        name_ar=name_ar,
        name_en=name_en,
        description_ar=description_ar,
        description_en=description_en,
        image_url=image_url,
        price_min=price_min,
        price_max=price_max,
        cost_per_unit=cost_per_unit,
        currency=currency,
    )
    db.add(product)
    db.flush()

    # Classify inline so the upload response already carries HS candidates. In
    # production this is the Celery ``classify_product`` task; here we call the
    # same service directly for a synchronous demo experience.
    if classify:
        llm = get_llm_provider()
        # Visual understanding first (DoD step 1): fill AR/EN description +
        # attributes, which then also inform the HS classification below.
        product_vision.describe_product(db, product, llm)
        hs_classifier.classify_product(db, product, llm)
        embedding = get_embedding_provider().embed(
            [f"{product.name_en} {product.description_en or ''}"]
        )[0]
        product.embedding = embedding

    db.commit()
    return ProductOut.model_validate(product)


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


@router.post("/products/{product_id}/classify", response_model=ProductOut)
def classify(db: DbDep, product: ProductModel = Depends(get_owned_product)) -> ProductOut:
    hs_classifier.classify_product(db, product, get_llm_provider())
    db.commit()
    return ProductOut.model_validate(product)


@router.put("/products/{product_id}/hs-code", response_model=ProductOut)
def confirm_hs(
    payload: HSConfirmRequest,
    db: DbDep,
    user: CurrentUser,
    product: ProductModel = Depends(get_owned_product),
) -> ProductOut:
    if db.get(HSCode, payload.hs_code) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown HS code {payload.hs_code}",
        )
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
