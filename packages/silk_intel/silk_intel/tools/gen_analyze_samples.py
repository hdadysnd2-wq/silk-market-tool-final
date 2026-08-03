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

    os.environ.pop("SILK_HERMETIC", None)


if __name__ == "__main__":
    main()
