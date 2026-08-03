"""سجلّا الملامح — Market & Product Profile Registries (طبقةُ التعميم، G1/G2).

المبدأُ الحاكم (طلبُ الأمر): **كلُّ حقيقةٍ خاصّةٍ بسوقٍ أو منتجٍ بيانات، وكلُّ
سلوكٍ قاعدةٌ تقرأ تلك البيانات.** لا اسمَ دولةٍ ولا رمزَ ISO ولا خطَّ HS ولا اسمَ
جهةِ معايير في ملفِّ منطق — تعيش حصراً في `data/market_profiles.json` و
`data/product_profiles.json`. إدخالُ سوقٍ/منتجٍ جديد = إضافةُ مدخلٍ + استشهاداته،
لا تعديلُ منطق.

هذه الوحدة **تحمّل وتتحقّق** فقط (لا سلوكَ خاصّ بسوق) — القواعدُ الواعيةُ
بالملامح (المعقولية/التعريفة/الاشتراطات/السلاسل) تقرأ منها في وحداتها.

الصيغةُ **JSON** بمكتبة stdlib (قرارُ المالك: لا اعتمادَ جديد؛ الإثباتُ البنيويّ
يعوّض غيابَ تعليقات YAML — provenance مُهيكَلٌ يُتحقَّق آلياً خيرٌ من تعليق). كلُّ
حقيقةٍ كائنٌ `{value, source_url, review_date}` + حقلا `note`/`reviewer` اختياريان.

عقدُ عدم الاختلاق ممتدٌّ للملامح: كلُّ حقيقةٍ **موثَّقةٌ** بـ`source_url` +
`review_date`؛ ملفٌّ مشوَّهٌ أو حقيقةٌ بلا استشهادٍ = **فشلٌ عالي الصوت** (لا
افتراضٌ صامت). المُحقِّقُ هو عقدُ الإدخال (G6): `python3 silk_profiles.py` قبل
الدمج — يطبع خطأً **لكلِّ حقلٍ** لا رسالةً عامّة.
"""
from __future__ import annotations

import functools
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
MARKET_PROFILES_PATH = os.path.join(_HERE, "data", "market_profiles.json")
PRODUCT_PROFILES_PATH = os.path.join(_HERE, "data", "product_profiles.json")


class ProfileError(ValueError):
    """ملفُ ملامحَ مشوَّهٌ أو حقيقةٌ بلا استشهاد — فشلٌ عالي الصوت، لا افتراض."""


# ── القيمُ المعدودة (enums) — أيُّ قيمةٍ خارجها ترفضها البوّابة ────────────────
REPORTING_TIERS = ("strong", "moderate", "weak")
PRODUCT_CLASSES = ("processed_food", "fresh_produce", "dried_produce",
                   "beverage", "non_food")
INGREDIENT_CLASSES = ("plant", "animal", "mixed")
TARIFF_LINKS = ("bloc_matrix", "wits", "wto", "mfn")
LOGISTICS_MODES = ("sea", "land", "air", "landlocked_corridor")
# مفرداتٌ مُتحكَّمٌ بها لفئات الإنتاج (مراجعةٌ ذاتية HIGH-5): مفتاحُ الانضمام
# الحمّالُ لـG4.1 (`product.production_category` ∈ `market.domestic_production`)
# **يجب** أن يُطابَق حرفياً — enum مشترَكٌ يمنع انحرافَ المفرد/المرادف
# (`groundnut` مقابل `groundnuts`) الذي كان سيُعيد علامةَ المعقولية الكاذبة
# لنيجيريا/الهند صامتةً. (مفرداتُ تصنيفٍ كـPRODUCT_CLASSES — لا هويّةَ سوق/HS؛
# توسيعُها عند فئةِ إنتاجٍ جديدةٍ نادرٌ كتوسيع product_class، حدٌّ مقبول.)
PRODUCTION_CATEGORIES = ("groundnuts", "dates", "dairy", "potatoes",
                         "vegetables", "cassava", "sorghum", "spices", "rice")

_CITED_KEYS = ("value", "source_url", "review_date")


# ── التحميل (مُخبّأ؛ يُمسَح في الاختبارات عبر reload_profiles) ─────────────────
def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        raise ProfileError(f"ملفُ الملامح مفقود: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"ملفُ الملامح JSON مشوَّه ({path}): {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ProfileError(f"ملفُ الملامح فارغٌ أو ليس خريطة: {path}")
    return data


@functools.lru_cache(maxsize=1)
def _market_registry() -> dict:
    return _load_json(MARKET_PROFILES_PATH)


@functools.lru_cache(maxsize=1)
def _product_registry() -> dict:
    return _load_json(PRODUCT_PROFILES_PATH)


def reload_profiles() -> None:
    """امسحِ التخبئة — للاختبارات التي تكتب ملفاً مؤقّتاً ثمّ تُحمّله."""
    _market_registry.cache_clear()
    _product_registry.cache_clear()


# ── مساعِدو الاستشهاد ────────────────────────────────────────────────────────
def cited_value(node: object, default: object = None) -> object:
    """قيمةُ حقيقةٍ موثَّقة (`{value, source_url, review_date}`) — أو الافتراض
    إن غابت. القارئون في وحدات القواعد يستعملونه فلا يلمسون بنيةَ الاستشهاد."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return default


def _check_cited(node: object, path: str, errors: list) -> None:
    """حقيقةٌ واحدةٌ يجب أن تكون `{value, source_url, review_date}` غيرَ فارغة."""
    if not isinstance(node, dict):
        errors.append(f"{path}: حقيقةٌ غيرُ موثَّقة — مطلوبٌ "
                      "{value, source_url, review_date}")
        return
    if "value" not in node:
        errors.append(f"{path}.value مفقود")
    for k in ("source_url", "review_date"):
        if not str(node.get(k) or "").strip():
            errors.append(f"{path}.{k} مفقودٌ (فجوةُ استشهادٍ — لا اختلاق)")
    # لا حقولٌ زائدةٌ صامتة (يمسك أخطاءً مطبعية) — «note»/«reviewer» اختياريان
    # (provenance مُهيكَلٌ يعوّض غيابَ تعليقات JSON — قرارُ المالك).
    extra = set(node) - set(_CITED_KEYS) - {"note", "reviewer"}
    if extra:
        errors.append(f"{path}: حقولٌ غيرُ معروفة {sorted(extra)}")


def _check_cited_list(node: object, path: str, errors: list,
                      min_len: int = 1) -> None:
    if not isinstance(node, list) or len(node) < min_len:
        errors.append(f"{path}: مطلوبةٌ قائمةٌ موثَّقةٌ (≥{min_len})")
        return
    for i, item in enumerate(node):
        _check_cited(item, f"{path}[{i}]", errors)


def _enum(node: object, allowed, path: str, errors: list,
          is_list: bool = False) -> None:
    _check_cited(node, path, errors)
    if not isinstance(node, dict) or "value" not in node:
        return
    vals = node["value"] if is_list else [node["value"]]
    if not isinstance(vals, list):
        errors.append(f"{path}.value: مطلوبةٌ قائمة")
        return
    bad = [v for v in vals if v not in allowed]
    if bad:
        errors.append(f"{path}.value: قيمٌ خارج المسموح {bad} (المسموح {list(allowed)})")


# ── تحقّقُ ملفِّ السوق ────────────────────────────────────────────────────────
def validate_market(iso3: str, prof: dict) -> list:
    """قائمةُ أخطاءٍ (فارغةٌ = صالح). يفرض حضورَ كلِّ قسمٍ وتوثيقَ كلِّ حقيقة."""
    e: list = []
    if not isinstance(prof, dict):
        return [f"{iso3}: المدخلُ ليس خريطة"]

    ident = prof.get("identity") or {}
    for f in ("iso3", "region", "currency", "fx_source_key"):
        _check_cited(ident.get(f), f"{iso3}.identity.{f}", e)
    if isinstance(ident.get("iso3"), dict) and \
            str(ident["iso3"].get("value") or "").upper() != iso3.upper():
        e.append(f"{iso3}.identity.iso3.value لا يطابق مفتاحَ المدخل")

    trade = prof.get("trade_regime") or {}
    _check_cited_list(trade.get("blocs"), f"{iso3}.trade_regime.blocs", e,
                      min_len=0)  # سوقٌ بلا تكتّلٍ مشروعة (قائمةٌ فارغةٌ موثَّقةٌ لا)
    _enum(trade.get("tariff_resolution_strategy"), TARIFF_LINKS,
          f"{iso3}.trade_regime.tariff_resolution_strategy", e, is_list=True)
    _check_cited(trade.get("mfn_default"), f"{iso3}.trade_regime.mfn_default", e)

    _enum(prof.get("reporting_quality"), REPORTING_TIERS,
          f"{iso3}.reporting_quality", e)

    reg = prof.get("regulatory_regime") or {}
    for f in ("standards_body", "labeling_languages", "halal_regime",
              "inspection_authority", "conformity_assessment"):
        _check_cited(reg.get(f), f"{iso3}.regulatory_regime.{f}", e)

    log = prof.get("logistics") or {}
    corridors = log.get("corridors")
    if not isinstance(corridors, list):
        e.append(f"{iso3}.logistics.corridors: مطلوبةٌ قائمة (قد تكون فارغةً "
                 "مع فجوةٍ معلنة)")
    else:
        for i, c in enumerate(corridors):
            _check_corridor(c, f"{iso3}.logistics.corridors[{i}]", e)

    ds = prof.get("data_sources") or {}
    for f in ("comtrade_reporter_files_netwgt", "connectors_available"):
        _check_cited(ds.get(f), f"{iso3}.data_sources.{f}", e)

    # الإنتاجُ المحليّ (يغذّي معقولية HF3 عبر (سوق×منتج)): قائمةٌ موثَّقةٌ بفئات
    # الإنتاج (من المفردات المُتحكَّم بها) التي يُعَدّ السوقُ منتِجاً مُعتبَراً لها
    # (قد تكون فارغة). HIGH-5: كلُّ فئةٍ ∈ PRODUCTION_CATEGORIES (لا انحرافَ مفرد).
    _enum(prof.get("domestic_production"), PRODUCTION_CATEGORIES,
          f"{iso3}.domestic_production", e, is_list=True)
    return e


def _check_corridor(c: object, path: str, errors: list) -> None:
    if not isinstance(c, dict):
        errors.append(f"{path}: مدخلُ ممرٍّ ليس خريطة")
        return
    # HIGH-4: `main_port` (بوّابةُ الوجهة) حقلٌ موثَّقٌ إلزاميّ — لا يُترَك بلا فحص.
    for k in ("origin", "destination", "mode", "main_port", "source_url",
              "review_date"):
        if not str(c.get(k) or "").strip():
            errors.append(f"{path}.{k} مفقود")
    if c.get("mode") not in LOGISTICS_MODES:
        errors.append(f"{path}.mode: {c.get('mode')!r} خارج {list(LOGISTICS_MODES)}")
    # زمنُ العبور حقيقةٌ موثَّقةٌ أو فجوةٌ معلنة (None + سببٌ) — لا اختلاق.
    tt = c.get("transit_time_days")
    if tt is None or (isinstance(tt, dict) and tt.get("value") is None):
        if not str(c.get("gap_reason") or "").strip():
            errors.append(f"{path}: زمنُ العبور غائبٌ بلا gap_reason معلن")
    else:
        _check_cited(tt, f"{path}.transit_time_days", errors)


# ── تحقّقُ ملفِّ المنتج ───────────────────────────────────────────────────────
def validate_product(key: str, prof: dict) -> list:
    e: list = []
    if not isinstance(prof, dict):
        return [f"{key}: المدخلُ ليس خريطة"]
    for f in ("hs_code", "parent_chapter", "unit_convention"):
        _check_cited(prof.get(f), f"{key}.{f}", e)
    _enum(prof.get("product_class"), PRODUCT_CLASSES, f"{key}.product_class", e)
    _enum(prof.get("ingredient_class"), INGREDIENT_CLASSES,
          f"{key}.ingredient_class", e)
    for f in ("storage_regime", "shelf_life_days"):
        _check_cited(prof.get(f), f"{key}.{f}", e)
    # فئةُ الإنتاج: تُوصَل بقائمة `domestic_production` في ملفِّ السوق فتُقرَّر
    # «إنتاجٌ محليٌّ مُعتبَر لهذا (السوق×المنتج)» بيانياً لا بفرعٍ في المنطق (G4.1).
    # HIGH-5: من المفردات المُتحكَّم بها — نفسُ enum قائمةِ السوق (لا انحرافَ مفتاح).
    _enum(prof.get("production_category"), PRODUCTION_CATEGORIES,
          f"{key}.production_category", e)

    band = prof.get("plausibility_band") or {}
    for f in ("per_capita_kg_min", "per_capita_kg_max"):
        _check_cited(band.get(f), f"{key}.plausibility_band.{f}", e)
    lo = cited_value((band or {}).get("per_capita_kg_min"))
    hi = cited_value((band or {}).get("per_capita_kg_max"))
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
        e.append(f"{key}.plausibility_band: الحدُّ الأدنى ({lo}) > الأعلى ({hi})")
    return e


# ── البوّابة العامّة ──────────────────────────────────────────────────────────
def validate_all(markets: dict | None = None,
                 products: dict | None = None) -> list:
    """كلُّ الأخطاء عبر السجلّين — تُستدعى في CI وفي عقد الإدخال (G6)."""
    markets = _market_registry() if markets is None else markets
    products = _product_registry() if products is None else products
    errors: list = []
    for iso3, prof in markets.items():
        errors += validate_market(iso3, prof)
    for key, prof in products.items():
        errors += validate_product(key, prof)
    # HIGH-5: انحرافُ مفتاح الانضمام (`groundnut` مقابل `groundnuts`) يمنعه
    # enum `PRODUCTION_CATEGORIES` المشترَك على الجانبين أعلاه — قيمةٌ خارجه
    # تفشل في **كلا** السجلّين. (لا فحصَ «يتيم»: منتجٌ لا تُنتِجه أيُّ سوقِ
    # وجهةٍ مشروعٌ تماماً — كلُّها تستورده، فـmarket_size ≈ imports.)
    return errors


def _assert_valid() -> None:
    errs = validate_all()
    if errs:
        raise ProfileError("ملامحُ غيرُ صالحة:\n- " + "\n- ".join(errs))


# ── المُوصِّلات (accessors) — القارئون في وحدات القواعد ───────────────────────
def market_profile(iso3: str) -> dict | None:
    """ملفُّ سوقٍ بالرمز ISO3 (غير حسّاسِ الحالة)، أو None إن لم يُعرَّف."""
    reg = _market_registry()
    return reg.get(str(iso3 or "").upper()) or reg.get(str(iso3 or ""))


def product_profile(hs_code: str) -> dict | None:
    """ملفُّ منتجٍ بخطِّ HS — يُطابَق على `hs_code.value` (لا مفتاحُ المدخل)."""
    hs = "".join(ch for ch in str(hs_code or "") if ch.isdigit())
    if not hs:
        return None
    for prof in _product_registry().values():
        if str(cited_value(prof.get("hs_code")) or "").replace(" ", "") == hs:
            return prof
    return None


def all_market_iso3() -> list:
    return sorted(_market_registry().keys())


def all_product_keys() -> list:
    return sorted(_product_registry().keys())


if __name__ == "__main__":  # عقدُ الإدخال (G6): «شغّل التحقّق»
    import sys
    _errs = validate_all()
    if _errs:
        print("INVALID PROFILES:")
        for _x in _errs:
            print(" -", _x)
        sys.exit(1)
    print(f"OK — {len(all_market_iso3())} سوق، {len(all_product_keys())} منتج، "
          "كلُّ حقيقةٍ موثَّقة.")
