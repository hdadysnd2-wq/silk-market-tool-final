"""Prompts and response schemas shared by the real and mock LLM adapters.

Both adapters answer against the same schemas, so the pipeline has exactly one
code path whether or not an API key is configured.
"""

from __future__ import annotations

from typing import Any

HS_SCHEMA_TITLE = "HSClassification"
EMAIL_SCHEMA_TITLE = "OutreachEmail"
PRODUCT_VISION_SCHEMA_TITLE = "ProductVision"

PRODUCT_VISION_SCHEMA: dict[str, Any] = {
    "title": PRODUCT_VISION_SCHEMA_TITLE,
    "type": "object",
    "required": ["description_en", "description_ar", "attributes"],
    "properties": {
        "description_en": {"type": "string", "description": "One-line English description"},
        "description_ar": {"type": "string", "description": "One-line Arabic description"},
        "attributes": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["name", "value"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
        },
    },
}

PRODUCT_VISION_SYSTEM_PROMPT = """You are a product analyst for a Saudi export house.
From a product image (and any text), describe the product for an export catalogue.

Rules:
- Give a concise one-line description in English and in Arabic.
- List the salient visible attributes (material, form, colour, packaging, size cues,
  apparent grade) as name/value pairs — only what is actually observable.
- Never invent an attribute you cannot see; omit it rather than guess."""


def product_vision_prompt(*, name: str, description: str | None, has_image: bool) -> str:
    parts = [f"Product name: {name}"]
    if description:
        parts.append(f"Seller description: {description}")
    parts.append(
        "An image of the product is attached; describe what you see."
        if has_image
        else "No image was provided; describe from the text alone."
    )
    return "\n".join(parts)


HS_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "title": HS_SCHEMA_TITLE,
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["code", "confidence"],
                "properties": {
                    "code": {"type": "string", "description": "Six-digit HS code"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

HS_SYSTEM_PROMPT = """You are a customs classification specialist working for a Saudi export house.
Given a product image and description, identify the three most likely six-digit HS codes.

Rules:
- Return exactly three candidates, most likely first.
- Codes must be valid six-digit HS6 codes with no punctuation.
- Confidence is your calibrated probability that the code is correct, 0 to 1.
- The rationale is one short sentence naming the deciding physical characteristic.
- Never invent a code to fill the list; if unsure, give a broader heading within the
  correct chapter and lower the confidence accordingly."""


def hs_user_prompt(
    *, name: str, description: str | None, sector: str | None, has_image: bool
) -> str:
    parts = [f"Product name: {name}"]
    if description:
        parts.append(f"Description: {description}")
    if sector:
        parts.append(f"Manufacturer sector: {sector}")
    parts.append(
        "An image of the product is attached."
        if has_image
        else "No product image was provided; classify from the text alone."
    )
    return "\n".join(parts)


OUTREACH_EMAIL_SCHEMA: dict[str, Any] = {
    "title": EMAIL_SCHEMA_TITLE,
    "type": "object",
    "required": ["subject", "body"],
    "properties": {
        "subject": {"type": "string", "maxLength": 120},
        "body": {"type": "string"},
    },
}

EMAIL_SYSTEM_PROMPT = """You write first-touch B2B export outreach emails on behalf of Saudi manufacturers.

Hard rules:
- Write entirely in the requested language.
- 90 to 140 words in the body. Short paragraphs, no bullet lists, no emoji.
- Open with the specific import evidence you are given; it is why this buyer was chosen.
- State one concrete reason the Saudi factory is worth a reply (capacity, certification,
  freight advantage, price band) drawn only from the facts provided.
- Close with a low-friction ask: a sample, a price list, or a short call.
- Never use spam-trigger phrasing: no "FREE", no "GUARANTEED", no "ACT NOW", no all-caps
  words, no exclamation marks, no invented figures, no fake prior contact.
- Do not write a signature block, an unsubscribe line, or a postal address; the platform
  appends the sender identity and unsubscribe link itself.
- Sound like a person at the factory wrote it, not a marketing department."""


def email_user_prompt(context: dict[str, Any]) -> str:
    lines = [
        f"Language for the email: {context['language_name']}",
        "",
        "Saudi factory (the sender):",
        f"- Name: {context['factory_name']}",
        f"- Sector: {context.get('factory_sector') or 'not specified'}",
        f"- About: {context.get('factory_description') or 'not specified'}",
        "",
        "Product being offered:",
        f"- Name: {context['product_name']}",
        f"- Description: {context.get('product_description') or 'not specified'}",
        f"- HS code: {context.get('hs_code') or 'not specified'}",
        f"- Price range: {context.get('price_range') or 'not specified'}",
        "",
        "Buyer being contacted:",
        f"- Company: {context['buyer_name']} ({context['buyer_country']})",
        f"- Industry: {context.get('buyer_industry') or 'not specified'}",
        f"- Contact: {context.get('contact_name') or 'unknown'},"
        f" {context.get('contact_title') or 'unknown role'}",
        "",
        f"Import evidence to open with: {context['import_evidence']}",
    ]
    return "\n".join(lines)
