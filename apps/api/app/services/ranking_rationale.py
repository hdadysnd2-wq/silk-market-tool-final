"""Deterministic one-line ranking rationale per market (transparent scoring, J1).

Pure functions, no LLM, no network: given the persisted ``score_components``
dict a Stage-2 row carries ({name: {value, source, note}}), emit an EN and an AR
one-liner naming the TOP TWO contributing components — ordered by the engine's
real model weights (``engine.component_weights()``, the ONE scoring model) —
with their actual values and sources. Every number in the line is a component
value the platform persisted; nothing is invented (I1). No components → ``None``
(a declared absence, not a filler sentence).
"""

from __future__ import annotations

#: Component display names (EN, AR) — the engine's seven, J1.
_LABELS: dict[str, tuple[str, str]] = {
    "market_size": ("market size", "حجم السوق"),
    "demand_capacity": ("demand capacity", "طاقة الطلب"),
    "saudi_position": ("Saudi supplier share", "حصة السعودية"),
    "unit_price_level": ("unit price level", "مستوى سعر الوحدة"),
    "tariff_access": ("applied tariff", "الرسوم الجمركية المطبقة"),
    "competition": ("supplier concentration", "تركّز المورّدين"),
    "logistics_proximity": ("distance from Jeddah", "المسافة من جدة"),
}


def _fmt_usd(value: float) -> str:
    """Compact, sane USD formatting: $1.2M / $530.0K / $950."""
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.0f}"


def _fmt_value(name: str, value: float) -> str:
    """Format one component value in its narrative unit (no unit invention).

    Units follow the component contracts in ``stage2._components_for``:
    market_size USD; demand_capacity PPP USD/capita; saudi_position
    percent-points; unit_price_level USD per reported qty unit; tariff_access a
    fraction (0.05 = 5%); competition a 0..1 concentration share;
    logistics_proximity km.
    """
    if name == "market_size":
        return _fmt_usd(value)
    if name == "demand_capacity":
        return _fmt_usd(value)
    if name == "saudi_position":
        return f"{value:.1f}%"
    if name == "unit_price_level":
        return f"${value:,.2f}/unit"
    if name == "tariff_access":
        return f"{value * 100:.1f}%"
    if name == "competition":
        return f"{value:.2f}"
    if name == "logistics_proximity":
        return f"{value:,.0f} km"
    return f"{value:,.2f}"


def _top_components(components: dict[str, dict]) -> list[tuple[str, dict]]:
    """The two heaviest PRESENT components, by the engine's real model weights.

    Deterministic: weight desc, then component name asc as a stable tiebreak.
    Only components with a numeric value count — an omitted/None component is a
    declared gap and can never be "a top contributor".
    """
    from app.services import engine

    weights = engine.component_weights()
    present = [
        (name, c)
        for name, c in components.items()
        if isinstance(c, dict) and isinstance(c.get("value"), (int, float))
    ]
    present.sort(key=lambda item: (-weights.get(item[0], 0.0), item[0]))
    return present[:2]


def build_rationale(components: dict[str, dict] | None) -> dict[str, str] | None:
    """EN + AR one-liners naming the top-2 contributing components, or ``None``.

    Returns ``{"en": ..., "ar": ...}``. Every figure in the line is a persisted
    component value with its source in parentheses — never a fabricated number
    (I1). ``None`` when no scored component exists (declared absence).
    """
    if not components:
        return None
    top = _top_components(components)
    if not top:
        return None

    en_parts: list[str] = []
    ar_parts: list[str] = []
    for name, c in top:
        value = float(c["value"])
        source = str(c.get("source") or "").strip() or "unknown source"
        label_en, label_ar = _LABELS.get(name, (name, name))
        formatted = _fmt_value(name, value)
        en_parts.append(f"{label_en} {formatted} ({source})")
        ar_parts.append(f"{label_ar} {formatted} ({source})")

    return {
        "en": "Ranked on " + " and ".join(en_parts) + ".",
        "ar": "رُتِّب بناءً على " + " و".join(ar_parts) + ".",
    }
