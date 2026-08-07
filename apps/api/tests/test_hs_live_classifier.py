"""Regression locks: HS classification through the engine's general classifier.

Wave 3 symptom A: the product was wired only to the offline CSV+difflib
resolver, whose two kill-gates failed 8/10 realistic product names with zero
candidates, while the engine's ``classify_general`` (deterministic-first,
Claude over the full WCO nomenclature when needed, no-fabrication validation,
spend caps, caching) was referenced nowhere in apps/. classify_product now
delegates to it through the seam; the offline path survives as the engine's
own explicit fallback with visible provenance.
"""

from __future__ import annotations

from app.models import HSCode, Product
from app.services import engine as engine_seam
from app.services import hs_classifier


def _mk_product(db, factory, **kw) -> Product:
    defaults = dict(factory_id=factory.id, name_ar="منتج", name_en="Widget", currency="USD")
    defaults.update(kw)
    p = Product(**defaults)
    db.add(p)
    db.commit()
    return p


def test_llm_result_maps_to_candidates_with_provenance(db, factory, monkeypatch):
    product = _mk_product(db, factory, name_en="Al Munawara Premium Sukkari Dates 1kg")

    canned = {
        "tier": "candidates",
        "hs6": None,
        "confidence": 0.0,
        "candidates": [
            {
                "hs6": "080410",
                "description_ar": "تمور",
                "reason_ar": "تمر معبأ",
                "confidence": 0.72,
            },
            # A real WCO code OUTSIDE the seed CSV — must be backfilled from the
            # engine's official reference, not dropped.
            {
                "hs6": "080450",
                "description_ar": "Guavas, mangoes",
                "reason_ar": "",
                "confidence": None,
            },
        ],
        "message": "اختر من المرشّحين",
        "source": "model",
        "used_llm": True,
    }
    monkeypatch.setattr(engine_seam, "classify_hs_general", lambda name, **kw: canned)

    candidates = hs_classifier.classify_product(db, product)

    assert product.classification_status == "classified"
    assert [c["code"] for c in candidates] == ["080410", "080450"]
    assert all(c["provider"] == "silk_hs_classifier (model)" for c in candidates)
    assert all(c["used_llm"] is True for c in candidates)
    # Measured confidence carried as-is; unscored stays honestly None (I1).
    assert candidates[0]["confidence"] == 0.72
    assert candidates[1]["confidence"] is None
    # Codes are FK-valid and confirmable even when outside the seed catalogue.
    for code in ("080410", "080450"):
        assert db.get(HSCode, code) is not None


def test_manual_tier_is_a_declared_gap_not_invented_candidates(db, factory, monkeypatch):
    product = _mk_product(db, factory, name_en="Unclassifiable Gadget X9")
    canned = {
        "tier": "manual",
        "hs6": None,
        "confidence": 0.0,
        "candidates": [{"hs6": "760611", "description_ar": "Aluminium plates"}],
        "message": "أدخل الرمز يدوياً",
        "source": "manual",
        "used_llm": False,
    }
    monkeypatch.setattr(engine_seam, "classify_hs_general", lambda name, **kw: canned)

    candidates = hs_classifier.classify_product(db, product)

    # Manual-tier suggestion rows are raw difflib noise — surfacing them as
    # proposals would be fabrication-adjacent. Declared gap instead.
    assert candidates == []
    assert product.classification_status == "failed"
    assert "يدوياً" in (product.failure_reason or "")


def test_keyless_deterministic_path_still_classifies_seed_names(db, factory):
    # No ANTHROPIC key in the suite: the engine's deterministic path must still
    # classify a clean seed name end-to-end (no LLM, no spend).
    product = _mk_product(db, factory, name_en="", name_ar="تمر")
    candidates = hs_classifier.classify_product(db, product)

    assert product.classification_status == "classified"
    assert candidates[0]["code"] == "080410"
    assert candidates[0]["used_llm"] is False
    assert "deterministic" in candidates[0]["provider"]


def test_vision_description_never_pollutes_the_query(db, factory, monkeypatch):
    # The old enriched query measurably LOWERED match scores (diagnosis repro);
    # only the bare name may reach the classifier — attributes travel as hints.
    product = _mk_product(
        db,
        factory,
        name_en="Sukkari Dates",
        description_en="A long vision-generated paragraph about premium gift boxes",
        attributes=[{"name": "packaging", "value": "vacuum sealed"}],
    )
    seen: dict = {}

    def _spy(name, **kw):
        seen["query"] = name
        seen["kw"] = kw
        return {"tier": "manual", "candidates": [], "message": "m", "source": "manual"}

    monkeypatch.setattr(engine_seam, "classify_hs_general", _spy)
    hs_classifier.classify_product(db, product)

    assert "vision-generated" not in seen["query"]
    assert seen["query"] == "Sukkari Dates منتج"
    assert seen["kw"]["ingredients"] == ["vacuum sealed"]


def test_hs_ai_allowed_follows_the_anthropic_key(monkeypatch):
    import app.config as config_mod
    from app.config import Settings

    assert engine_seam.hs_ai_allowed() is False  # suite runs keyless

    keyed = Settings(anthropic_api_key="sk-test")
    monkeypatch.setattr(config_mod, "get_settings", lambda: keyed)
    assert engine_seam.hs_ai_allowed() is True
