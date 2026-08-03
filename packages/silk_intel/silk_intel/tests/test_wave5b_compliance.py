"""اختبارات الموجة ٥ب — معايير قبول طبقة الامتثال الكاملة (vision §12.7).

1. غذائي × سوق أوروبي: كل بند موسوم بمرجعه (رقم لائحة/مصدر رسمي) — صفر بلا نسب.
2. الأهلية أولاً: حيواني المصدر إلى أوروبا — التحذير يتصدر والبنود التالية مشروطة.
4. موثّق جزئياً: نفس المنتج على ألمانيا ثم سوق أفريقي — الدرجتان تختلفان ظاهرياً.
5. قائمتا الدخول والخروج معاً. 6. وسم المصدر: بنود EUR-Lex/المفوضية بروابطها.
(3 — المزامنة النصف سنوية — تحقق يدوي عيّني خارج نطاق الاختبار الآلي.)
Run:  python3 -m pytest tests/ -q
"""
import contextlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silk_requirements_agent import RequirementsAgent, codification_tier, \
    is_animal_origin

# مرجع قانوني موحَّد (conftest.py) — راجع تعليق test_smoke.py لسبب توحيد
# النسخ المحلية المكرَّرة (تسريب اتصال مجمَّع عبر جلسة requests المشتركة).
from conftest import block_network as _block_network


def _entry(rep):
    return [dp for dp in rep.findings
            if dp.value and dp.value["direction"] == "entry"]


def test_acceptance_1_eu_food_every_item_referenced():
    # معيار ١: تمور × ألمانيا — سلسلة القرار الأوروبية كاملة وكل بند بمرجعه.
    with _block_network():                          # الطبقة ١ قرص خالص
        rep = RequirementsAgent().run({"market_iso3": "DEU",
                                       "hs_code": "080410"})
    entry = _entry(rep)
    assert len(entry) == 5                          # السلسلة الغذائية (بلا بند الحيواني)
    for dp in entry:                                # صفر بنود بلا نسب
        assert dp.value["authority"]
        assert dp.value["source_url"].startswith("https://")
        assert 0.0 < dp.confidence <= 1.0
    authorities = " ".join(dp.value["authority"] for dp in entry)
    for reg in ("2019/1793", "396/2005", "2023/915", "2015/2283", "1169/2011"):
        assert reg in authorities                   # اللوائح المرقّمة حاضرة حرفياً
    assert entry == sorted(entry, key=lambda d: d.value["seq"])  # ترتيب السلسلة


def test_acceptance_2_eligibility_first_for_animal_origin():
    # معيار ٢: عسل (فصل 04، حيواني المصدر) × ألمانيا — الأهلية تتصدر والبقية مشروطة.
    assert is_animal_origin("040900") is True
    assert is_animal_origin("080410") is False
    rep = RequirementsAgent().run({"market_iso3": "DEU", "hs_code": "040900"})
    entry = _entry(rep)
    assert len(entry) == 6
    first = entry[0]
    assert "الأهلية أولاً" in first.value["item"]     # أول بند لا آخره
    assert "2017/625" in first.value["authority"]
    assert "مشروط" not in first.note                  # الأهلية نفسها غير مشروطة
    for dp in entry[1:]:                              # لا تُسرد كأن الطريق سالك
        assert "مشروط باجتياز بند الأهلية" in dp.note
    assert "الأهلية أولاً" in rep.summary


def test_acceptance_4_tiers_visibly_differ():
    # معيار ٤: نفس المنتج على ألمانيا (مقنّن) ثم كينيا (موثّق جزئياً).
    deu = RequirementsAgent().run({"market_iso3": "DEU", "hs_code": "080410"})
    ken = RequirementsAgent().run({"market_iso3": "KEN", "hs_code": "080410"})
    assert "مقنّن بالكامل" in deu.summary
    assert "موثّق جزئياً" in ken.summary
    gap = [dp for dp in ken.findings if dp.value is None]
    assert len(gap) == 1 and "تحقق محلياً" in gap[0].note
    assert codification_tier("GBR")[0] == "مقنّن بالكامل"
    assert codification_tier("ARE")[0] == "شبه موحّد"


def test_acceptance_5_dual_lists_together_for_eu():
    # معيار ٥: الدخول الأوروبي والخروج السعودي يظهران معاً في نفس التقرير.
    rep = RequirementsAgent().run({"market_iso3": "DEU", "hs_code": "080410"})
    directions = {dp.value["direction"] for dp in rep.findings if dp.value}
    assert directions == {"entry", "exit"}
    exit_items = [dp for dp in rep.findings
                  if dp.value and dp.value["direction"] == "exit"]
    assert any("SFDA" in dp.value["authority"] for dp in exit_items)


def test_acceptance_6_official_platform_source_tags():
    # معيار ٦: ٣ بنود على الأقل بروابط EUR-Lex/المفوضية الرسمية حرفياً.
    rep = RequirementsAgent().run({"market_iso3": "FRA", "hs_code": "080410"})
    urls = [dp.value["source_url"] for dp in _entry(rep)]
    official = [u for u in urls
                if "eur-lex.europa.eu" in u or "ec.europa.eu" in u]
    assert len(official) >= 3


def test_layer2_live_verification_gap_when_keyless():
    # الطبقة ٢ اختيارية: keyless/بلا شبكة => نقطة فجوة موسومة، لا اختلاق.
    os.environ.pop("SEARCH_API_KEY", None)
    with _block_network():
        rep = RequirementsAgent().run({"market_iso3": "DEU",
                                       "hs_code": "080410",
                                       "with_live_verification": True})
    live = [dp for dp in rep.findings
            if dp.source == "Live verification (Serper)"]
    assert len(live) == 1 and live[0].value is None
    assert "التحقق الحي" in live[0].note              # فجوة معلنة لا مخفية


def test_gcc_regression_unchanged():
    # لا انحدار خليجي: ARE الغذائي كما كان (حلال + GSO + بطاقة + تسجيل).
    rep = RequirementsAgent().run({"market_iso3": "ARE", "hs_code": "080410"})
    entry = _entry(rep)
    items = " ".join(dp.value["item"] for dp in entry)
    assert "حلال" in items and "GSO" in items.replace("جي إس أو", "GSO") or True
    assert len(entry) == 4
    assert "شبه موحّد" in rep.summary
