"""Deterministic LLM stand-in used whenever no model API key is configured.

It answers against the same JSON schemas as the Anthropic adapter, so the
classifier and drafting services cannot tell the two apart. Classification is a
keyword table over the seeded HS catalogue; drafting is a per-language template.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Template

from app.providers.base import LLMMessage, LLMResponse
from app.providers.determinism import rng_for
from app.providers.llm.prompts import (
    EMAIL_SCHEMA_TITLE,
    HS_SCHEMA_TITLE,
    PRODUCT_VISION_SCHEMA_TITLE,
)

FIXTURES = Path(__file__).resolve().parents[2] / "seeds" / "fixtures"

#: Body templates per language. They deliberately mirror the real prompt's rules:
#: import evidence first, one concrete reason, low-friction ask, no spam triggers.
EMAIL_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "subject": "{{ product_name }} from a Saudi manufacturer",
        "body": """Dear {{ contact_first_name }},

{{ import_evidence }} That is why I am writing to you directly.

{{ factory_name }} manufactures {{ product_name }} in Saudi Arabia{% if hs_code %} \
(HS {{ hs_code }}){% endif %}. {{ factory_pitch }}{% if price_range %} Our current \
indicative range is {{ price_range }}.{% endif %}

If it is useful, I can send a specification sheet and a sample to \
{{ buyer_name }}, or arrange a short call at a time that suits you.

Kind regards,
{{ sender_name }}""",
    },
    "es": {
        "subject": "{{ product_name }} de un fabricante saudí",
        "body": """Estimado/a {{ contact_first_name }}:

{{ import_evidence }} Por eso le escribo directamente.

{{ factory_name }} fabrica {{ product_name }} en Arabia Saudí\
{% if hs_code %} (HS {{ hs_code }}){% endif %}. {{ factory_pitch }}\
{% if price_range %} Nuestro rango indicativo actual es {{ price_range }}.{% endif %}

Si le resulta útil, puedo enviar una ficha técnica y una muestra a {{ buyer_name }}, \
o concertar una breve llamada cuando le venga bien.

Un cordial saludo,
{{ sender_name }}""",
    },
    "pt": {
        "subject": "{{ product_name }} de um fabricante saudita",
        "body": """Prezado(a) {{ contact_first_name }},

{{ import_evidence }} É por isso que escrevo diretamente.

A {{ factory_name }} fabrica {{ product_name }} na Arábia Saudita\
{% if hs_code %} (HS {{ hs_code }}){% endif %}. {{ factory_pitch }}\
{% if price_range %} A nossa faixa indicativa atual é {{ price_range }}.{% endif %}

Se for útil, posso enviar uma ficha técnica e uma amostra para {{ buyer_name }}, \
ou marcar uma breve chamada no horário que preferir.

Atenciosamente,
{{ sender_name }}""",
    },
    "fr": {
        "subject": "{{ product_name }} d'un fabricant saoudien",
        "body": """Bonjour {{ contact_first_name }},

{{ import_evidence }} C'est la raison pour laquelle je vous écris directement.

{{ factory_name }} fabrique {{ product_name }} en Arabie saoudite\
{% if hs_code %} (HS {{ hs_code }}){% endif %}. {{ factory_pitch }}\
{% if price_range %} Notre fourchette indicative actuelle est {{ price_range }}.{% endif %}

Si cela vous est utile, je peux envoyer une fiche technique et un échantillon à \
{{ buyer_name }}, ou convenir d'un bref appel au moment qui vous convient.

Cordialement,
{{ sender_name }}""",
    },
    "hi": {
        "subject": "{{ product_name }} — सऊदी निर्माता से",
        "body": """नमस्ते {{ contact_first_name }},

{{ import_evidence }} इसी कारण मैं आपको सीधे लिख रहा हूँ।

{{ factory_name }} सऊदी अरब में {{ product_name }} का निर्माण करती है\
{% if hs_code %} (HS {{ hs_code }}){% endif %}। {{ factory_pitch }}\
{% if price_range %} हमारी वर्तमान संकेतात्मक सीमा {{ price_range }} है।{% endif %}

यदि उपयोगी हो, तो मैं {{ buyer_name }} को विशिष्टता पत्रक और नमूना भेज सकता हूँ, \
या आपकी सुविधा अनुसार एक छोटी कॉल तय कर सकता हूँ।

सादर,
{{ sender_name }}""",
    },
}

FACTORY_PITCHES = [
    "We hold export-grade certification and ship regularly from Jeddah Islamic Port, "
    "which usually puts us a week ahead of East Asian suppliers on your lane.",
    "Our line runs to international specification and we can hold stock for repeat "
    "monthly orders rather than one-off containers.",
    "We supply to specification in mixed-SKU containers, which keeps working capital "
    "lower than the full-container minimums most mills insist on.",
]


class MockLLMProvider:
    """Schema-compatible stand-in for a hosted model."""

    name = "mock_llm"
    model = "mock-deterministic-v1"

    def __init__(self, keywords_path: Path | None = None) -> None:
        self._keywords_path = keywords_path or (FIXTURES / "hs_keywords.json")
        self._keywords: list[dict[str, Any]] | None = None

    @property
    def keywords(self) -> list[dict[str, Any]]:
        if self._keywords is None:
            if self._keywords_path.exists():
                self._keywords = json.loads(self._keywords_path.read_text(encoding="utf-8"))
            else:  # pragma: no cover - fixtures ship with the repo
                self._keywords = []
        return self._keywords

    # -- protocol ----------------------------------------------------------

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        return self._dispatch(prompt, json_schema)

    def complete_with_image(
        self,
        *,
        system: str,
        prompt: str,
        image_bytes: bytes | None,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        return self._dispatch(prompt, json_schema)

    # -- internals ---------------------------------------------------------

    def _dispatch(self, prompt: str, json_schema: dict[str, Any] | None) -> LLMResponse:
        title = (json_schema or {}).get("title")
        if title == HS_SCHEMA_TITLE:
            parsed = self._classify(prompt)
        elif title == EMAIL_SCHEMA_TITLE:
            parsed = self._draft_email(prompt)
        elif title == PRODUCT_VISION_SCHEMA_TITLE:
            parsed = self._describe(prompt)
        else:
            parsed = None
        text = json.dumps(parsed, ensure_ascii=False) if parsed else "(mock response)"
        return LLMResponse(text=text, provider_name=self.name, model=self.model, parsed=parsed)

    def _classify(self, prompt: str) -> dict[str, Any]:
        """Score the HS keyword table against the prompt text."""
        haystack = prompt.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self.keywords:
            hits = sum(1 for kw in entry["keywords"] if kw.lower() in haystack)
            if hits:
                scored.append((hits / len(entry["keywords"]), entry))

        scored.sort(key=lambda pair: (-pair[0], pair[1]["code"]))

        if not scored:
            # Nothing matched: fall back to a stable pick so the pipeline still
            # produces three reviewable candidates for the user to override.
            fallback = self.keywords[:3] or [
                {"code": "999999", "description": "Unclassified", "keywords": []}
            ]
            return {
                "candidates": [
                    {
                        "code": entry["code"],
                        "confidence": round(0.34 - 0.08 * idx, 2),
                        "rationale": "No distinctive keyword matched; broad guess only.",
                    }
                    for idx, entry in enumerate(fallback[:3])
                ]
            }

        candidates = []
        for idx, (ratio, entry) in enumerate(scored[:3]):
            confidence = round(min(0.94, 0.55 + 0.4 * ratio) - 0.15 * idx, 2)
            candidates.append(
                {
                    "code": entry["code"],
                    "confidence": max(confidence, 0.05),
                    "rationale": f"Matched on {entry['description'].lower()}.",
                }
            )
        return {"candidates": candidates}

    def _describe(self, prompt: str) -> dict[str, Any]:
        """Deterministic product understanding (AR/EN description + attributes).

        The mock cannot see the image, so it derives an honest stand-in from the
        prompt text (the real vision adapter does the real work once keyed). Values
        are deterministic so the pipeline is reproducible offline.
        """
        name = _prompt_field(prompt, "Product name:") or "the product"
        seller = _prompt_field(prompt, "Seller description:")
        attributes: list[dict[str, str]] = [{"name": "origin", "value": "Saudi Arabia"}]
        if seller:
            attributes.append({"name": "seller_note", "value": seller})
        for token in [t for t in name.replace(",", " ").split() if len(t) > 3][:4]:
            attributes.append({"name": "keyword", "value": token})
        return {
            "description_en": f"{name} — a Saudi-made product prepared for export.",
            "description_ar": f"{name} — منتج سعودي الصنع مُجهَّز للتصدير.",
            "attributes": attributes,
        }

    def _draft_email(self, prompt: str) -> dict[str, Any]:
        ctx = _parse_email_prompt(prompt)
        lang = ctx.get("language", "en")
        tpl = EMAIL_TEMPLATES.get(lang, EMAIL_TEMPLATES["en"])
        rng = rng_for(ctx.get("buyer_name", ""), ctx.get("product_name", ""))
        render_ctx = dict(ctx)
        render_ctx["factory_pitch"] = rng.choice(FACTORY_PITCHES)
        return {
            "subject": Template(tpl["subject"]).render(**render_ctx),
            "body": Template(tpl["body"]).render(**render_ctx),
        }


def _prompt_field(prompt: str, label: str) -> str | None:
    """Read the value of a ``label: value`` line out of a built prompt, or None."""
    for line in prompt.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip() or None
    return None


def _parse_email_prompt(prompt: str) -> dict[str, Any]:
    """Recover the drafting context from the prompt the service built.

    The real adapter hands the same prompt to a model; the mock reads it back so
    both produce a personalized message from identical inputs.
    """
    ctx: dict[str, Any] = {
        "language": "en",
        "contact_first_name": "there",
        "buyer_name": "your company",
        "product_name": "our product",
        "factory_name": "our factory",
        "sender_name": "Export Manager",
        "hs_code": "",
        "price_range": "",
        "import_evidence": "",
    }
    lang_names = {
        "english": "en",
        "spanish": "es",
        "portuguese": "pt",
        "french": "fr",
        "hindi": "hi",
    }
    for raw in prompt.splitlines():
        line = raw.strip()
        if line.startswith("Language for the email:"):
            ctx["language"] = lang_names.get(line.split(":", 1)[1].strip().lower(), "en")
        elif line.startswith("- Company:"):
            company = line.split(":", 1)[1].strip()
            ctx["buyer_name"] = company.split(" (")[0]
        elif line.startswith("- Name:") and ctx["factory_name"] == "our factory":
            ctx["factory_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Name:"):
            ctx["product_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("- HS code:"):
            value = line.split(":", 1)[1].strip()
            ctx["hs_code"] = "" if value == "not specified" else value
        elif line.startswith("- Price range:"):
            value = line.split(":", 1)[1].strip()
            ctx["price_range"] = "" if value == "not specified" else value
        elif line.startswith("- Contact:"):
            value = line.split(":", 1)[1].strip()
            name = value.split(",")[0].strip()
            if name and name.lower() != "unknown":
                ctx["contact_first_name"] = name.split()[0]
        elif line.startswith("Import evidence to open with:"):
            ctx["import_evidence"] = line.split(":", 1)[1].strip()
    return ctx
