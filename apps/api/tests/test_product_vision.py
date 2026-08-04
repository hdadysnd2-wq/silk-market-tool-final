"""Visual product understanding (DoD step 1): image → AR/EN description + attributes.

The vision pass fills a bilingual description and salient attributes, without ever
overwriting a description the factory typed itself. Runs deterministically on the
mock offline.
"""

from __future__ import annotations

from app.models import Product
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.prompts import PRODUCT_VISION_SCHEMA, product_vision_prompt
from app.providers.registry import get_llm_provider
from app.services.product_vision import describe_product


def test_mock_vision_returns_bilingual_description_and_attributes():
    llm = MockLLMProvider()
    resp = llm.complete_with_image(
        system="s",
        prompt=product_vision_prompt(name="Medjool Dates", description=None, has_image=True),
        image_bytes=None,
        json_schema=PRODUCT_VISION_SCHEMA,
    )
    parsed = resp.parsed
    assert parsed["description_en"] and parsed["description_ar"]
    assert any(a["name"] == "origin" for a in parsed["attributes"])


def _product(db, factory, **kw) -> Product:
    p = Product(factory_id=factory.id, name_ar="تمر", name_en="Medjool Dates", currency="USD", **kw)
    db.add(p)
    db.commit()
    return p


def test_describe_fills_missing_description_and_attributes(db, factory):
    product = _product(db, factory)
    describe_product(db, product, get_llm_provider())
    assert product.description_en  # filled from the vision pass
    assert product.description_ar
    assert product.attributes  # non-empty visual attributes


def test_describe_never_overwrites_a_seller_description(db, factory):
    product = _product(db, factory, description_en="Our own copy", description_ar="نصّنا")
    describe_product(db, product, get_llm_provider())
    assert product.description_en == "Our own copy"  # untouched
    assert product.description_ar == "نصّنا"
    assert product.attributes  # attributes are still added


def test_create_product_endpoint_returns_attributes(client, auth_headers, db, factory):
    # The intake pipeline is async: POST is accepted (202) with the product still
    # pending; the vision pass ran eagerly during the POST, so GET carries it.
    res = client.post(
        "/api/v1/products",
        headers=auth_headers,
        data={"name_ar": "عسل السدر", "name_en": "Sidr Honey", "classify": "true"},
    )
    assert res.status_code == 202, res.text
    accepted = res.json()
    assert accepted["task_id"]
    assert accepted["product"]["classification_status"] == "pending"

    body = client.get(f"/api/v1/products/{accepted['product']['id']}", headers=auth_headers).json()
    assert body["attributes"]  # the vision pass populated attributes
    assert body["description_en"]  # and filled a description
