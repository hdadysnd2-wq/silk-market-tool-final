"""يولّد عيّنات /analyze الأربع من تشغيلة حتمية واحدة — لا شبكة، مخزن مبذور.

المشكلة (مراجعة "أرقام منفصلة بلا معنى"، PR الخلاصة الاحترافية + ترابط
/analyze): عيّنات `report_full_latest.md`/`.docx`/`analysis_latest.json`
الملتزَمة كانت راكدة — أقدم من طبقة السرد (P1) وحزمة البحث (Stage 3، §4b)
وقسم "الأسواق المرشّحة الأخرى" الجديد، فلا تعكس السلوك الحالي لطبقة العرض
(قاعدة §10.6: كل تعديل على طبقة العرض يُعيد توليد عيّناته). هذه الأداة
تشغّل محرّك حتمي حقيقي (سوقان مبذوران: الصين والإمارات) داخل حاجز شبكة
صادق، ثم تشتق الأربعة من نفس النتيجة — بلا اختلاق، كل رقم بمصدره.

Usage:  python3 tools/gen_analyze_samples.py
"""
import contextlib
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLES_DIR = os.path.join(_REPO_ROOT, "samples")


@contextlib.contextmanager
def _block_network():
    """اقطع الشبكة مؤقتاً — نفس نمط tests/conftest.py::block_network."""
    real = socket.socket

    def _no_net(*a, **k):
        raise OSError("network disabled for sample generation")

    socket.socket = _no_net
    try:
        yield
    finally:
        socket.socket = real


def _seed_store() -> None:
    import silk_store
    silk_store.migrate()
    silk_store.upsert_trade_flows([
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 4.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2022, "flow": "M", "value_usd": 5.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 6.0e7, "qty_kg": 2.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "IRN",
         "year": 2023, "flow": "M", "value_usd": 3.0e7},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.8e7, "qty_kg": 8.0e6},
        {"hs6": "080410", "reporter_iso3": "CHN", "partner_iso3": "TUN",
         "year": 2023, "flow": "M", "value_usd": 1.2e7},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2021, "flow": "M", "value_usd": 1.5e7},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "WLD",
         "year": 2023, "flow": "M", "value_usd": 2.0e7, "qty_kg": 5.0e6},
        {"hs6": "080410", "reporter_iso3": "ARE", "partner_iso3": "SAU",
         "year": 2023, "flow": "M", "value_usd": 1.4e7, "qty_kg": 4.0e6},
    ])


def _executive_payload() -> dict:
    """حمولة «التقرير التنفيذي متعدد الأسواق» الحتمية الموسومة — نفس عقد
    result["executive"] الذي يغذّيه جانب المنتج (منصّة silk). كل صف موسوم
    «عيّنة توضيحية» صراحةً (نمط SILK_HERMETIC نفسه — بيانات موسومة لا حية)،
    وسوقان ناقصان عمداً (بلا أسعار / بلا مشترين) ليُظهر النموذج سطرَي الفجوة
    المعلنة «سعر غير مرصود» و«لا مشترون مرصودون بعد لهذا السوق»."""
    _at = "2026-08-01"

    def _rc(value, source, note):
        return {"value": value, "source": f"{source} (عيّنة توضيحية)",
                "confidence": 0.85, "note": note, "retrieved_at": _at}

    def _mkt(country, iso3, iso2, score, conf, tags, transit, prices,
             competitors, buyers):
        return {
            "country": country, "iso3": iso3, "iso2": iso2,
            "score": score, "score_confidence": conf,
            "rationale_components": {
                "market_size": _rc(6.0e7 if iso3 == "CHN" else 2.0e7,
                                   "UN Comtrade", "واردات 2023"),
                "saudi_position": _rc(30.0 if iso3 == "CHN" else 70.0,
                                      "UN Comtrade", "حصة سعودية 2023"),
                "demand_capacity": _rc(None, "World Bank",
                                       "تعذّر الجلب في التشغيلة الحتمية"),
                "competition": _rc(0.25 if iso3 == "CHN" else 0.49,
                                   "UN Comtrade", "تركّز الموردين HHI"),
            },
            "tags": tags, "transit_hub": transit,
            "prices": prices, "competitors": competitors, "buyers": buyers,
        }

    chn_prices = [
        {"competitor": "علامة تمور منافسة أ (عيّنة توضيحية)", "price": 12.5,
         "currency": "USD", "store": "متجر إلكتروني صيني",
         "url": "https://shop.sample/dates-a", "source": "رصد ويب (عيّنة)",
         "confidence": 0.6, "retrieved_at": _at},
        {"competitor": "علامة تمور منافسة ب (عيّنة توضيحية)", "price": 9.8,
         "currency": "USD", "store": "سوبرماركت",
         "url": "https://shop.sample/dates-b", "source": "رصد ويب (عيّنة)",
         "confidence": 0.55, "retrieved_at": _at}]
    chn_competitors = [
        {"exporter_name": "إيران", "share_pct": 50.0, "value_usd": 3.0e7,
         "source": "UN Comtrade (عيّنة توضيحية)", "confidence": 0.9,
         "retrieved_at": _at},
        {"exporter_name": "السعودية", "share_pct": 30.0, "value_usd": 1.8e7,
         "source": "UN Comtrade (عيّنة توضيحية)", "confidence": 0.9,
         "retrieved_at": _at},
        {"exporter_name": "تونس", "share_pct": 20.0, "value_usd": 1.2e7,
         "source": "UN Comtrade (عيّنة توضيحية)", "confidence": 0.9,
         "retrieved_at": _at}]
    chn_buyers = [
        {"name": "مستورد أغذية — شنغهاي (عيّنة توضيحية)",
         "source": "خرائط الويب (عيّنة)", "confidence": 0.5,
         "relevance_score": 0.8, "contacts": 2, "legal_review_required": True},
        {"name": "موزّع جملة — قوانغتشو (عيّنة توضيحية)",
         "source": "خرائط الويب (عيّنة)", "confidence": 0.45,
         "relevance_score": 0.6, "contacts": 1,
         "legal_review_required": False}]
    are_competitors = [
        {"exporter_name": "السعودية", "share_pct": 70.0, "value_usd": 1.4e7,
         "source": "UN Comtrade (عيّنة توضيحية)", "confidence": 0.9,
         "retrieved_at": _at}]
    return {
        "screening": {"total_screened": 38, "analysis_status": "complete",
                      "analysis_at": f"{_at}T00:00:00Z"},
        "markets": [
            _mkt("الصين", "CHN", "CN", 0.62, 0.72,
                 ["سوق كبير", "نموّ واردات"], False,
                 chn_prices, chn_competitors, chn_buyers),
            # سوق بلا أسعار مرصودة — يُظهر سطر «سعر غير مرصود» المعلن.
            _mkt("الإمارات", "ARE", "AE", 0.55, 0.66,
                 ["حضور سعودي قائم"], True, [], are_competitors, []),
        ],
    }


def main() -> None:
    os.environ["SILK_HERMETIC"] = "1"
    _seed_store()

    import silk_engine
    with _block_network():
        result = silk_engine.analyze(
            "تمور", countries=[{"iso3": "CHN", "m49": "156"},
                              {"iso3": "ARE", "m49": "784"}],
            year=2023, with_research=True, with_requirements=True,
            with_risk=True, with_trend=True)

    from silk_render import build_view
    view = build_view(result)
    result["view"] = view

    from silk_reports import render_markdown, render_docx, render_brief
    md_path = os.path.join(_SAMPLES_DIR, "report_full_latest.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(view))
    print("wrote", md_path)

    docx_path = os.path.join(_SAMPLES_DIR, "report_full_latest.docx")
    render_docx(view, docx_path)
    print("wrote", docx_path)

    brief_path = os.path.join(_SAMPLES_DIR, "brief_latest.txt")
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(render_brief(view))
    print("wrote", brief_path)

    # analysis_latest.json — نفس شكل ردّ POST /analyze الحقيقي (result + view)
    # حرفياً: api.py._json(result) بعد إرفاق result["view"] — دون المرور عبر
    # TestClient (حاجز الشبكة يكسر نقل TestClient الداخلي — راجع اتفاقية
    # الاختبارات في CLAUDE.md)، فنستعمل مُسلسِل الـ API نفسه مباشرة.
    from api import _to_jsonable
    payload = _to_jsonable(result)
    json_path = os.path.join(_SAMPLES_DIR, "analysis_latest.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("wrote", json_path)

    # التقرير التنفيذي متعدد الأسواق — نسخة ثانية من نفس نتيجة المحرّك
    # الحتمية مع حمولة executive موسومة (عقد جانب المنتج)، عبر مسار الإنتاج
    # نفسه حصراً: build_view ثم render_executive_docx. نسخة مستقلة كي تبقى
    # العيّنات الأربع أعلاه ممثِّلة لردّ /analyze الفعلي (بلا executive).
    exec_result = dict(result)
    exec_result.pop("view", None)
    exec_result["executive"] = _executive_payload()
    exec_view = build_view(exec_result)
    from silk_reports import render_executive_docx
    exec_path = os.path.join(_SAMPLES_DIR, "report_executive_latest.docx")
    render_executive_docx(exec_view, exec_path)
    print("wrote", exec_path)

    os.environ.pop("SILK_HERMETIC", None)


if __name__ == "__main__":
    main()
