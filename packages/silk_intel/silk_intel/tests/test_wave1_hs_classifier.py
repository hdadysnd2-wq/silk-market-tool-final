"""Wave 1 — ذكاء ما قبل التشغيل (مندوبات المالك): مُصنِّف HS + بوّابة HS الصلبة
+ استشارة بلد المنشأ — قفلٌ سلوكيّ هرمتيّ.

عائلتان في السجلّ:
- `unresolved-hs-silent-spend` (حادثة الفيتوتشيني: أُنفِق $ والغلاف «—»
  والركيزة التجارية فجوة حرجة). البوّابة الصلبة تجعلها **مستحيلة**.
- `hardcoded-product-rule` (نفس عائلة «التمور السعودية» — المنصّة عُضّت مرّةً
  بترميز اسم منتج). القفل يثبت أنّ الحارسين قاعدتان مبنيّتان على البيانات لا
  على أسماء: زيرو منتج/دولة/HS مكتوب صلبًا، والقاعدة تُعمَّم من ≥٤ عيّنات
  متنوّعة (فيتوتشيني/إيطاليا عيّنةٌ واحدةٌ فقط لا حالة).

هرمتي: الشبكة محجوبة (`requests` مُرقَّعة أو `resolve_all` حتمي بلا شبكة)،
والبيئة معزولة عبر `_env`، وعدّاد السقف على ملفٍ مؤقّت.
"""
import contextlib
import importlib
import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_hs_classifier as hsc  # noqa: E402
import silk_market_ranker as ranker  # noqa: E402


@contextlib.contextmanager
def _env(**vals):
    """اضبط متغيرات بيئة مع استرجاع مضمون — set env vars, guaranteed restore."""
    old = {k: os.environ.get(k) for k in vals}
    try:
        for k, v in vals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _block_net():
    """ارفع OSError على أيّ requests — offline (لا كلمة hermetic في النص)."""
    return mock.patch("requests.sessions.Session.request",
                      side_effect=OSError("network disabled for offline test"))


# ═══════════════════ ١) المُصنِّف: عقد عدم الاختلاق ═══════════════════════════

def test_classifier_offline_or_no_key_never_fabricates():
    """بلا كلود (لا مفتاح/شبكة) => منتقٍ يدوي بلا اختلاق: hs6=None, ثقة 0.0,
    الرسالة الموحّدة. منتجٌ مجهولٌ تمامًا لا يُطابِق المرجع بثقة."""
    with _env(ANTHROPIC_API_KEY=None), _block_net():
        out = hsc.classify("qwxzptvbmzzz منتج غير موجود إطلاقاً",
                           allow_claude=True)
    assert out["status"] == "manual"
    assert out["hs6"] is None
    assert out["confidence"] == 0.0
    assert out["message"] == hsc.MANUAL_MSG
    assert "تعذّر التصنيف" in out["rationale_ar"]


def test_validate_rejects_offreference_and_excluded_codes():
    """عقد عدم الاختلاق في `_validate`: رمزٌ خارج المرجع أو في فصلٍ مستبعَد
    (٢٧) يُرفَض تمامًا (None) — لا فصل مختلَق. رمزٌ صحيحٌ من المرجع يُقبَل."""
    from silk_hs_resolver import load_hs_codes
    codes = {str(r.get("hs_code") or "").strip()
             for r in load_hs_codes() if r.get("hs_code")}
    real = next((c for c in codes if c[:2] != "27"), None)
    assert real, "المرجع فارغ — تهيئة خاطئة"
    # رمزٌ غير موجود في المرجع إطلاقًا (مُشتقّ ديناميكيًا) => رفض.
    absent = next(f"{n:06d}" for n in range(100000, 1000000)
                  if f"{n:06d}" not in codes and f"{n:06d}"[:2] != "27")
    assert hsc._validate({"hs6": absent, "confidence": 0.9}) is None
    # فصل بترولي مستبعَد (٢٧) => رفض حتى لو رقمٌ حقيقي الشكل.
    assert hsc._validate({"hs6": "270900", "confidence": 0.9}) is None
    # رمزٌ حقيقيّ من المرجع => يُقبَل بشكل الاقتراح.
    ok = hsc._validate({"hs6": real, "confidence": 0.8,
                        "rationale_ar": "س", "alternates": []})
    assert ok and ok["hs6"] == real and ok["source"] == "claude"


def test_deterministic_confident_path_makes_zero_claude_calls():
    """مُحلِّلٌ حتمي واثق (منتجٌ معروف) => اقتراح فوري بلا أيّ نداء كلود."""
    with mock.patch("silk_ai_judge._call",
                    side_effect=AssertionError("كلود لا يجب أن يُستدعى")) as m:
        out = hsc.classify("rice", allow_claude=True)
    assert m.call_count == 0
    assert out["status"] == "ok" and out["source"] == "deterministic"
    assert out["hs6"] and out["confidence"] >= 0.7


def test_claude_proposal_is_grounded_and_isolated():
    """نداءُ كلود: كلّ نصٍّ خارجي (المنتج/المكوّنات) يمرّ عبر `_isolate`،
    والرمز المُقترَح مُرسًى على المرجع (يُقبَل رمزٌ حقيقيّ من الأرز)."""
    captured = {}

    def fake_call(system, user, **kw):
        captured["user"] = user
        return '{"hs6":"100630","confidence":0.86,"rationale_ar":"حبوب أرز",' \
               '"alternates":[{"hs6":"100640","label":"أرز مكسور"}]}'

    with _env(ANTHROPIC_API_KEY="k", SILK_API_KEY="s"), \
         mock.patch("silk_ai_judge._call", side_effect=fake_call):
        out = hsc.classify("zzxq غامض", ingredients=["أرز", "ملح"],
                           category="حبوب", allow_claude=True)
    assert "[RAW_FINDINGS_START]" in captured["user"], "لم يُعزَل النصّ الخارجي"
    assert "أرز" in captured["user"] and "غامض" in captured["user"]
    assert out["status"] == "ok" and out["source"] == "claude"
    assert out["hs6"] == "100630" and out["alternates"], out


def test_claude_offreference_code_falls_back_to_manual_not_fabrication():
    """كلود أعاد رمزًا خارج المرجع => يُرفَض ويسقط للمنتقي اليدوي (لا اختلاق)."""
    with _env(ANTHROPIC_API_KEY="k"), \
         mock.patch("silk_ai_judge._call",
                    return_value='{"hs6":"424242","confidence":0.99}'):
        out = hsc.classify("zzxq غامض", allow_claude=True)
    assert out["status"] == "manual" and out["hs6"] is None


# ═══════════════════ ٢) نقطة النهاية /classify_hs — القياس ════════════════════

def _client():
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.create_app())


def test_endpoint_deterministic_needs_no_key_no_reservation():
    """منتجٌ معروفٌ بلا التباس => اقتراح حتمي 200 بلا مفتاح/حجز (الموجة ٣:
    شكل `classify_general` — tier/candidates لا status/alternates القديم)."""
    pytest.importorskip("fastapi")
    with _env(SILK_API_KEY=None, ANTHROPIC_API_KEY=None), _block_net():
        r = _client().post("/classify_hs", json={"product": "تمور"})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "auto" and body["source"] == "deterministic" \
        and body["hs6"] == "080410"


def test_endpoint_low_confidence_is_metered_count_from_the_cap():
    """منتجٌ غامضٌ + الصمّام مفعّل + مفتاح: النداء الأول يحجز تفعيلةً من
    السقف (`used_llm=True`)، والثاني (السقف=١ مستنفد) يتدهور بلا كلود
    (`used_llm=False`) — لا 429 على مسارٍ مجاني."""
    pytest.importorskip("fastapi")
    fake = '{"candidates":[{"hs6":"100630","description_ar":"أرز","reason_ar":"x","confidence":0.8}]}'
    with tempfile.TemporaryDirectory() as td:
        usage = os.path.join(td, "usage.db")
        with _env(SILK_HS_CLASSIFIER="1", ANTHROPIC_API_KEY="k",
                  SILK_API_KEY="s", SILK_PAID_DAILY_CAP="1",
                  SILK_USAGE_DB=usage, SILK_PAID_DAILY_USD_CAP=None), \
             mock.patch("silk_ai_judge.available", return_value=True), \
             mock.patch("silk_ai_judge._call", return_value=fake):
            c = _client()
            h = {"X-API-Key": "s"}
            r1 = c.post("/classify_hs", json={"product": "zzxq غامض"}, headers=h)
            r2 = c.post("/classify_hs", json={"product": "zzxq غامض٢"}, headers=h)
    assert r1.status_code == 200 and r1.json()["used_llm"] is True
    # الثاني (منتجٌ مختلفٌ — لا إصابة ذاكرة): السقف مستنفد => بلا كلود.
    assert r2.status_code == 200 and r2.json()["used_llm"] is False


def test_endpoint_dollar_cap_blocks_and_degrades_to_manual():
    """سقفٌ دولاريٌّ أدنى من تكلفة التصنيف المتوقَّعة => يُحجَب النداء ويتدهور
    بلا كلود (دولار-metered، يُغلق نمط تدقيق #6 لهذا المسار)."""
    pytest.importorskip("fastapi")
    with tempfile.TemporaryDirectory() as td:
        usage = os.path.join(td, "usage.db")
        with _env(SILK_HS_CLASSIFIER="1", ANTHROPIC_API_KEY="k",
                  SILK_API_KEY="s", SILK_USAGE_DB=usage,
                  SILK_PAID_DAILY_USD_CAP="0.001",
                  SILK_HS_CLASSIFY_EXPECTED_USD="0.02"), \
             mock.patch("silk_ai_judge.available", return_value=True), \
             mock.patch("silk_ai_judge._call",
                        return_value='{"candidates":[{"hs6":"100630","confidence":0.8}]}') as m:
            r = _client().post("/classify_hs", json={"product": "zzxq غامض"},
                               headers={"X-API-Key": "s"})
    assert r.status_code == 200
    assert r.json()["used_llm"] is False and r.json()["hs6"] is None
    assert m.call_count == 0, "لا يجب أن يُستدعى كلود بعد حجب السقف الدولاري"


def test_endpoint_disabled_or_no_key_degrades_to_manual_never_fabricates():
    """الصمّام مُطفأ (افتراضي) على منتجٍ منخفض الثقة => تدهورٌ 200، لا
    اختلاق ولا نداء كلود (السلوك كاليوم)."""
    pytest.importorskip("fastapi")
    with _env(SILK_HS_CLASSIFIER=None, SILK_API_KEY=None), _block_net():
        r = _client().post("/classify_hs", json={"product": "zzxq غامض"})
    assert r.status_code == 200
    assert r.json()["tier"] in ("candidates", "manual")
    assert r.json()["hs6"] is None


# ═══════════════════ ٣) بوّابة HS الصلبة — حادثة الفيتوتشيني ═══════════════════

def test_research_hard_gate_422_on_empty_hs6_no_reservation():
    """عائلة unresolved-hs-silent-spend: SILK_REQUIRE_HS6=1 + منتجٌ لا يُحلّ
    => /research 422 **قبل** أيّ حجز دولاري. الدفتر الدولاري يبقى صفرًا (لم
    يُنفَق قرشٌ على رمزٍ مجهول) — حادثة الفيتوتشيني مستحيلة."""
    pytest.importorskip("fastapi")
    import silk_usage
    with tempfile.TemporaryDirectory() as td:
        usage = os.path.join(td, "usage.db")
        with _env(SILK_REQUIRE_HS6="1", SILK_API_KEY=None,
                  ANTHROPIC_API_KEY=None, SILK_USAGE_DB=usage,
                  SILK_PAID_DAILY_USD_CAP="10"), _block_net():
            r = _client().post("/research", json={
                "product": "qwxzptvbmzzz منتج مجهول", "market": "Italy"})
            spent = silk_usage.usd_spent_today(usage)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "unresolved_hs"
    assert spent == 0.0, f"أُنفِق مالٌ على رمز HS مجهول: {spent}"


def test_research_flag_off_tolerates_empty_hs6_todays_way():
    """الصمّام مُطفأ (افتراضي) => نفس السلوك اليوم: لا 422 unresolved_hs —
    يمرّ لبوّابة الجهوزية (409 بلا مفتاح كلود). توافق خلفي كامل."""
    pytest.importorskip("fastapi")
    with _env(SILK_REQUIRE_HS6=None, SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net():
        r = _client().post("/research", json={
            "product": "qwxzptvbmzzz منتج مجهول", "market": "Italy"})
    assert r.status_code != 422 or r.json()["detail"].get("error") != "unresolved_hs"


# ═══════════════════ ٤) استشارة بلد المنشأ — قاعدة مبنيّة على البيانات ═════════
# عيّناتٌ متنوّعة (فيتوتشيني/إيطاليا واحدةٌ منها فقط): القاعدة تُعمَّم من
# البيانات لا من الأسماء. المصدر مُرقَّع (world_export_totals) كي يبقى الاختبار
# هرمتيًا ويثبت أنّ الإطلاق/الصمت يتبع الترتيب لا اسمَ الدولة/المنتج.

_FAKE_EXPORTERS = {
    "190219": ["ITA", "CHN", "DEU", "TUR", "BEL", "THA"],   # معكرونة — إيطاليا
    "150910": ["ESP", "ITA", "GRC", "TUN", "PRT", "FRA"],   # زيت زيتون — إسبانيا
    "080410": ["TUN", "IRN", "SAU", "IRQ", "DZA", "ISR"],   # تمور — لا GBR
    "040900": ["CHN", "ARG", "UKR", "IND", "MEX", "ESP"],   # عسل — لا ARE
}


def _fake_world_export_totals(hs_code, year):
    codes = _FAKE_EXPORTERS.get(str(hs_code), [])
    return [{"iso3": c, "m49": "0", "total_usd": 100 - i}
            for i, c in enumerate(codes)]


@pytest.mark.parametrize("hs,iso3,expected", [
    ("190219", "ITA", True),    # معكرونة + إيطاليا => يُطلَق
    ("150910", "ESP", True),    # زيت زيتون + إسبانيا => يُطلَق
    ("080410", "GBR", False),   # تمور + بريطانيا => صامت
    ("040900", "ARE", False),   # عسل + الإمارات => صامت
])
def test_producer_advisory_generalizes_from_data_not_names(hs, iso3, expected):
    """القاعدة تُعمَّم من ترتيب البيانات: الإطلاق يتبع «من أكبر ٥ مصدّرين» لا
    اسمَ الدولة/المنتج. ≥٤ عيّنات متنوّعة تُثبت التعميم."""
    with mock.patch.object(ranker, "world_export_totals",
                           side_effect=_fake_world_export_totals):
        is_top, top = ranker.is_top_world_exporter(hs, iso3, 2023)
    assert is_top is expected
    if expected:
        assert iso3 in {t["iso3"] for t in top}


def test_producer_advisory_topn_is_env_driven_not_hardcoded():
    """العتبة config-driven: SILK_PRODUCER_ADVISORY_TOPN=2 يُضيّق المجموعة
    فتخرج دولةٌ كانت ضمن أكبر ٥ — لا رقم مكتوب صلبًا."""
    with mock.patch.object(ranker, "world_export_totals",
                           side_effect=_fake_world_export_totals):
        with _env(SILK_PRODUCER_ADVISORY_TOPN="2"):
            is_top, _ = ranker.is_top_world_exporter("150910", "GRC", 2023)
    assert is_top is False   # اليونان الثالثة => خارج أكبر اثنين


def test_producer_advisory_fails_open_silent_on_probe_failure():
    """تعذّر تحديد المصدّرين (شبكة/كومتريد) => صامت (False, []) لا تحذيرٌ كاذب."""
    with mock.patch.object(ranker, "world_export_totals",
                           side_effect=OSError("net blocked")):
        is_top, top = ranker.is_top_world_exporter("190219", "ITA", 2023)
    assert is_top is False and top == []


def test_research_producer_advisory_422_until_explicit_consent():
    """نهاية-لنهاية: سوقٌ منتِجة + الصمّام مفعّل => 422 استشاري قبل الحجز؛
    ثم `producer_ack=true` يعبر البوّابة (لا يعود 422 الاستشاري)."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRODUCER_ADVISORY="1", SILK_PRODUCER_ADVISORY_TOPN="5",
              SILK_API_KEY=None, ANTHROPIC_API_KEY=None), _block_net(), \
         mock.patch.object(ranker, "world_export_totals",
                           side_effect=_fake_world_export_totals):
        c = _client()
        body = {"product": "معكرونة", "market": "Italy", "hs_code": "190219"}
        r1 = c.post("/research", json=body)
        r2 = c.post("/research", json=dict(body, producer_ack=True))
    assert r1.status_code == 422
    assert r1.json()["detail"]["error"] == "producer_country_advisory"
    assert "ITA" in r1.json()["detail"]["top_exporters"]
    # مع الموافقة: تعبر الاستشارة (تصل بوّابة الجهوزية 409 بلا مفتاح).
    assert not (r2.status_code == 422
                and r2.json()["detail"].get("error") == "producer_country_advisory")


def test_research_producer_advisory_silent_for_non_producer_market():
    """سوقٌ ليست من أكبر المصدّرين (تمور/بريطانيا) => لا 422 استشاري إطلاقًا."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRODUCER_ADVISORY="1", SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net(), \
         mock.patch.object(ranker, "world_export_totals",
                           side_effect=_fake_world_export_totals):
        r = _client().post("/research", json={
            "product": "تمور", "market": "United Kingdom", "hs_code": "080410"})
    assert not (r.status_code == 422
                and r.json()["detail"].get("error") == "producer_country_advisory")


def test_research_producer_advisory_flag_off_never_fires():
    """الصمّام مُطفأ (افتراضي) => لا استشارة حتى لسوقٍ منتِجة (السلوك كاليوم)."""
    pytest.importorskip("fastapi")
    with _env(SILK_PRODUCER_ADVISORY=None, SILK_API_KEY=None,
              ANTHROPIC_API_KEY=None), _block_net(), \
         mock.patch.object(ranker, "world_export_totals",
                           side_effect=_fake_world_export_totals):
        r = _client().post("/research", json={
            "product": "معكرونة", "market": "Italy", "hs_code": "190219"})
    assert not (r.status_code == 422
                and r.json()["detail"].get("error") == "producer_country_advisory")


# ═══════════════════ ٥) القفل العام — لا ترميز منتج/دولة/HS ═══════════════════

def test_classifier_and_advisory_paths_have_no_hardcoded_product_or_iso_or_hs():
    """عائلة hardcoded-product-rule: منطقُ الحارسين (المُصنِّف + دوالّ الاستشارة)
    يخلو من أيّ اسم منتج أو رمز دولة (ISO3) أو رمز HS من عيّنات الاختبار —
    القاعدة تعمل من البيانات وحدها. العتبة config-driven (env) لا رقم صلب."""
    import inspect
    import re
    sources = [inspect.getsource(hsc)]
    for fn in (ranker.world_export_totals, ranker.top_world_exporters,
               ranker.is_top_world_exporter, ranker._producer_advisory_topn):
        sources.append(inspect.getsource(fn))
    blob = "\n".join(sources)

    def _present(tok: str) -> bool:
        # لاتينيّ: مطابقةُ كلمةٍ كاملة (كي لا تُطابق «dates» جزءَ «candidates»).
        if tok.isascii():
            return re.search(r"(?<![A-Za-z0-9])" + re.escape(tok)
                             + r"(?![A-Za-z0-9])", blob) is not None
        return tok in blob            # عربيّ: تطابق نصّي مباشر يكفي

    # أسماء منتجات/عيّنات، رموز دول العيّنات، ورموز HS العيّنات — يجب ألّا تظهر.
    forbidden = [
        # منتجات
        "معكرونة", "pasta", "fettuccine", "تمور", "dates", "زيت زيتون",
        "olive", "عسل", "honey", "التمور السعودية",
        # رموز دول العيّنات
        "ITA", "ESP", "GBR", "ARE",
        # رموز HS العيّنات
        "190219", "150910", "080410", "040900",
    ]
    leaked = [tok for tok in forbidden if _present(tok)]
    assert not leaked, f"ترميزٌ صلبٌ لمنتج/دولة/HS في منطق الحارس: {leaked}"
    # العتبة config-driven (لا رقم صلب في المنطق العام).
    assert "SILK_PRODUCER_ADVISORY_TOPN" in blob


def test_web_prerun_flow_is_wired():
    """قفلٌ هرمتيّ لتدفّق ما قبل التشغيل في الواجهة (نظير _guard_export_format_
    contract): الدوالّ + المعالجات موجودةٌ فعلًا فلا يُشحَن تدفّقٌ ميت."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    for needle in (
        "function ensureHs(", "function showHsCandidates(",
        "function showHsManual(", "function showProducerAdvisory(",
        "function startResearch(", '"/classify_hs"',
        "producer_ack:true", 'd.error==="producer_country_advisory"',
        'd.error==="unresolved_hs"', 'd.error==="hs_confirmation_needed"',
        "S.cfg", "تأكيد رمز HS",
        "تعذّر التصنيف — اختر الرمز يدويًا",
    ):
        assert needle in html, f"وصلة تدفّق ما قبل التشغيل مفقودة: {needle}"
    # التدفّق يمرّ عبر ensureHs قبل التشغيل (لا استدعاء startResearch مباشرةً من الزرّ).
    assert "ensureHs(function(){startResearch({})})" in html, \
        "runDeepResearch لا يمرّ عبر ensureHs قبل التشغيل"
    # التأكيد بنقرة قبل **كل** تشغيل حين الصمّام مفعّل (مندوب المالك): لا خروج
    # مبكر يتخطّى نافذة التأكيد لمجرّد أن الرمز محسوم من القائمة.
    assert "if(S.hs){return cb()}" not in html, \
        "ensureHs يتخطّى نافذة التأكيد حين S.hs محسوم — يخالف «تأكيد قبل الحجز»"


def test_web_ui_never_shows_auto_badge_from_unverified_source():
    """قفلٌ بنيويّ (الموجة ٤ — بلاغ «UI-ONLY FIX»): شارة «✓ صُنّف تلقائياً»
    نصٌّ حرفيٌّ واحدٌ في كامل الملف، وموقعه الوحيد داخل `ensureHs` مشروطًا
    بـ`res.tier==="auto"` — قرار الحسم يعيش في نقطة الاختناق (endpoint)
    وحدها؛ أيّ مسار واجهةٍ ثانٍ يعرض الشارة من مصدرٍ آخر هو بالضبط عائلة
    الخطأ («زبدة الفول السوداني» ← ثقة زائفة) التي أُغلِقت هنا.

    الحارس يغطّي مسارَي البيانات الخام اللذين كانا يتجاوزان البوّابة قبل هذا
    الإصلاح: نقر صفّ الفهرس (`#pDrop`) واستقبال الصورة (`#intakeGo`) — كلاهما
    يجب أن يمرّ عبر `ensureHs(...)` حين المصنّف مفعّل، لا أن يضبط
    `S.hsConfirmed=true` مباشرةً من رمزٍ غير محقَّق."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()

    badge = "✓ صُنّف تلقائياً"
    count = html.count(badge)
    assert count == 1, (
        f"شارة «{badge}» ظهرت {count} مرّة — يجب أن تكون نقطة انطلاقٍ واحدة "
        "فقط داخل ensureHs؛ ظهورٌ إضافيٌّ يعني مساراً واجهةً ثانياً يختلق "
        "ثقةً بلا بوّابة"
    )

    ensure_hs_start = html.index("function ensureHs(")
    # الدالة التالية تبدأ نطاق ensureHs — الشارة يجب أن تقع قبلها لتكون
    # فعليًا "داخل" ensureHs (نفس نمط الفحص البنيويّ في الاختبار أعلاه).
    next_fn_start = html.index("function _pct(", ensure_hs_start)
    ensure_hs_body = html[ensure_hs_start:next_fn_start]
    assert badge in ensure_hs_body, (
        "شارة «✓ صُنّف تلقائياً» انتقلت خارج ensureHs — نقطة الاختناق الوحيدة "
        "لقرار الحسم يجب أن تبقى هناك"
    )
    assert 'res.tier==="auto"' in ensure_hs_body, (
        "ensureHs لم يعد يفرّع على res.tier==='auto' قبل عرض الشارة — "
        "بلا هذا الشرط تُعرَض الشارة على رمزٍ غير محسوم"
    )
    # الشارة تقع بعد الشرط نصّيًا (لا قبل الفرع) — تأكيدٌ بسيط لترتيب الكود.
    assert ensure_hs_body.index('res.tier==="auto"') < ensure_hs_body.index(badge)

    # مساران كانا يتجاوزان ensureHs (بلاغ الموجة ٤): كِلاهما يستدعي
    # ensureHs الآن حين المصنّف مفعّل، بدل ضبط hsConfirmed مباشرةً من رمزٍ خام.
    pdrop_start = html.index('$("#pDrop").addEventListener("click"')
    pdrop_end = html.index("\n\n", pdrop_start)
    pdrop_body = html[pdrop_start:pdrop_end]
    assert "ensureHs(function(){})" in pdrop_body, (
        "معالج نقر صفّ الفهرس (#pDrop) لا يمرّ عبر ensureHs — يعيد فخّ "
        "الثقة العمياء برمز الفهرس الخام"
    )

    intake_go_start = html.index('$("#intakeGo").addEventListener("click"')
    intake_go_body = html[intake_go_start:intake_go_start + 800]
    assert "ensureHs(function(){})" in intake_go_body, (
        "معالج تأكيد استخلاص الصورة (#intakeGo) لا يمرّ عبر ensureHs — "
        "يعيد فخّ الثقة العمياء برمز /resolve الخام"
    )


def test_classifier_module_has_no_hardcoded_hs_literal():
    """المُصنِّف لا يحمل أيّ رمز HS من ٤–٦ أرقام مكتوب صلبًا (يعمل من المرجع)."""
    import inspect
    import re
    src = inspect.getsource(hsc)
    # نطاق الأسطر الفعليّة (بلا docstring المثال JSON الذي يحوي NNNNNN).
    codes = re.findall(r"(?<!\d)\d{4,6}(?!\d)", src)
    assert not codes, f"رمز HS مكتوب صلبًا في المُصنِّف: {codes}"
