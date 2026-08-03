"""وكيل التعريفات الجمركية لسِلك — Silk customs-tariff research agent.

Best-effort applied import tariff (%) for an HS code into a market from World
Bank WITS (SDMX REST, TRN datasource). WITS is volatile, so every fetch is
defensive: on failure / format change / empty -> DataPoint(value=None,
confidence=0.0) + warning. Never guesses a rate (founding principle).
"""
from __future__ import annotations

import datetime
import logging
import xml.etree.ElementTree as ET

import requests

import silk_blocs
from silk_data_layer import DataPoint, ISO3_TO_M49, M49_TO_ISO3, _today
from silk_agents import BaseAgent, AgentReport

log = logging.getLogger(__name__)

# WITS SDMX REST — reported tariff by reporter/partner/product/year.
# Path: .../TRN/reporter/{num}/partner/{num}/product/{hs6}/year/{y}/datatype/reported
_WITS_BASE = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter"
_TIMEOUT = 30

# أعضاء الاتحاد الأوروبي — تعريفاتهم تُبلَّغ لـWITS تحت مُبلِّغ واحد هو
# الاتحاد الأوروبي (رمز 918) لأن التعريفة الخارجية موحّدة؛ الاستعلام برمز
# العضو الفردي (هولندا 528 مثلاً) لا يعيد صفوف TRN — هذا أصل فجوة التعريفة
# المزمنة في تقارير الأسواق الأوروبية (بلاغ حي، تشغيلة تمور/هولندا الثالثة).
_EU_ISO3 = silk_blocs.EU27  # المصدر الواحد لعضوية الاتحاد (DEF-2)
_EU_WITS_CODE = "918"


def _wits_reporter_code(iso3: str) -> tuple[str | None, bool]:
    """رمز المُبلِّغ الرقمي لـWITS — (الرمز، هل هو الاتحاد الأوروبي؟).

    بلاغ حي (تشغيلة ثالثة): WITS كان يرفض الطلب بـ"400 WITSAPIError/
    Invalid_Reporter" لأن الكود أرسل ISO3 الأبجدي ("NLD") بينما واجهة
    WITS SDMX تتوقع رموز الأمم المتحدة الرقمية (528 لهولندا، 000 للعالم
    — راجع أمثلة توثيق WITS نفسها: reporter/840/partner/000/...).
    عضو الاتحاد الأوروبي يُحوَّل لرمز الاتحاد (918) لأن تعريفته تُبلَّغ
    على مستوى الاتحاد حصراً. None = لا رمز رقمي معروف (فجوة معلنة، لا
    تخمين)."""
    iso3 = (iso3 or "").upper()
    if iso3 in _EU_ISO3:
        return _EU_WITS_CODE, True
    m49 = ISO3_TO_M49.get(iso3)
    return (m49.zfill(3) if m49 else None), False


# أعضاء الاتحاد الجمركي الخليجي — ثابت معاهدة (ميثاق مجلس التعاون، الاتحاد
# الجمركي 2003، gcc-sg.org). السعودية طرف المنشأ فلا صفّ لها في مرجع
# agreements_l1.csv (نطاقه الأسواق المستهدفة فقط)؛ العضوية هنا للتحقق من
# الطرفين معاً قبل خدمة الإعفاء البيني الموثّق.
_GCC_MEMBERS = silk_blocs.GCC  # المصدر الواحد لعضوية الخليج (DEF-2)


def _gcc_documented_exemption(hs_code: str, market_iso3: str,
                              partner_iso3: str) -> DataPoint | None:
    """الرُتبة الموثّقة: إعفاء الاتحاد الجمركي الخليجي البيني من مرجع الاتفاقيات.

    بلاغ حي (زبدة الفول السوداني/الكويت): فجوة «يفترض صفراً بموجب GCC لكن لا
    توثيق رقمي» بينما المرجع الموثّق موجود في `data/agreements_l1.csv` (صفّ
    GCC: «إعفاء كامل بين الأعضاء»، GCC secretariat). تُخدَم 0.0 فقط حين يكون
    **كلا** الطرفين عضوين وللسوق صفّ GCC member في المرجع — موسومةً مرجعاً
    قانونياً موثّقاً (`status="documented_agreement"`) لا رصداً تعريفياً حياً،
    وبشرط شهادة المنشأ معلَناً في الملاحظة. عضوية GAFTA («شبه كامل») لا تكفي
    لرقم؛ أي شرط ناقص => None فتبقى الفجوة معلنة (لا صفر مختلَق).
    قراءة CSV محلية فقط — صفر نداء شبكة في هذه الرُتبة."""
    market = (market_iso3 or "").upper()
    partner = (partner_iso3 or "").upper()
    if market not in _GCC_MEMBERS or partner not in _GCC_MEMBERS:
        return None
    import csv
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "agreements_l1.csv")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            lines = [ln for ln in f if not ln.lstrip().startswith("#")]
        rows = list(csv.DictReader(lines))
    except Exception as e:  # noqa: BLE001 — مرجع غائب = لا رُتبة موثّقة، فجوة
        log.warning("agreements reference unavailable (%s): %s", path, e)
        return None
    row = next((r for r in rows
                if (r.get("iso3") or "").strip().upper() == market
                and (r.get("agreement") or "").strip() == "GCC"
                and (r.get("status") or "").strip() == "member"), None)
    if row is None:
        return None
    try:
        conf = float(row.get("confidence") or 0.75)
    except (TypeError, ValueError):
        conf = 0.75
    src_url = (row.get("source_url") or "").strip()
    note = (f"إعفاء جمركي كامل بين أعضاء الاتحاد الجمركي الخليجي لرمز "
            f"HS{_hs6(hs_code)} ({partner}→{market}) — مرجع اتفاقيات موثّق "
            f"({row.get('tariff_effect', '')})، لا رصد تعريفي حي من WITS/WTO؛ "
            f"يتطلب شهادة منشأ خليجية. المصدر: {src_url}")
    return DataPoint(0.0, (row.get("source") or "GCC secretariat").strip(),
                     conf, note, _today(), status="documented_agreement")


def _default_year() -> int:
    """آخر سنة على الأرجح متاحة في WITS — بيانات التعريفة أبطأ من التجارة
    العادية عادةً، فنؤخّرها سنتين إضافيتين؛ محسوبة لا رقماً ثابتاً يتقادم."""
    return datetime.date.today().year - 3


def _hs6(hs_code: str) -> str:
    """رمز HS بست خانات — WITS keys on 6-digit HS (zero-padded, trimmed)."""
    digits = "".join(ch for ch in str(hs_code) if ch.isdigit())
    return (digits + "000000")[:6] if digits else ""  # "" signals invalid HS


def applied_tariff(
    hs_code: str,
    market_iso3: str,
    partner_iso3: str = "SAU",
    year: int | None = None,
) -> DataPoint:
    """التعريفة المطبّقة (%) — applied import tariff for HS into market from partner.

    Queries WITS TRN (AHS simple-average). Returns DataPoint(value=percent) on a
    parsed rate, else DataPoint(None, confidence=0.0, note=reason) on any error.
    """
    hs6 = _hs6(hs_code)
    if not hs6:
        return DataPoint(None, "World Bank WITS", 0.0,
                         f"invalid HS code {hs_code!r}", _today())
    year = year or _default_year()
    # رموز رقمية إلزامية (بلاغ حي: Invalid_Reporter مع ISO3 الأبجدي) —
    # المُبلِّغ عبر _wits_reporter_code (يشمل تحويل عضو الاتحاد الأوروبي
    # إلى 918)، والشريك عبر ISO3_TO_M49 مباشرة.
    reporter_code, is_eu = _wits_reporter_code(market_iso3)
    partner_m49 = ISO3_TO_M49.get((partner_iso3 or "").upper())
    if not reporter_code or not partner_m49:
        missing = market_iso3 if not reporter_code else partner_iso3
        return DataPoint(
            None, "World Bank WITS", 0.0,
            f"لا رمز رقمي معروف لـ{missing!r} في فهرس WITS — فجوة معلنة "
            "(لا استعلام بلا رمز صحيح)", _today())
    # datatype=reported: قيم التعريفة المُبلَّغة فعلاً — القيمتان الصالحتان
    # في واجهة WITS SDMX هما reported/aveestimated لا "AHS" (كانت خطأً
    # ثانياً كامناً خلف Invalid_Reporter).
    url = (f"{_WITS_BASE}/{reporter_code}/partner/{partner_m49.zfill(3)}"
           f"/product/{hs6}/year/{year}/datatype/reported")
    params = {"format": "JSON"}
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        rate = _parse_rate(r)
    except requests.exceptions.HTTPError as e:
        # WITS يعيد 400 (لا 404/200-فارغ) حين لا توجد بيانات تعريفة مُبلَّغة
        # لهذا الثلاثي (مُبلِّغ/شريك/منتج/سنة) — شائع لاقتصادات لا تُبلِّغ
        # جداول تعريفتها بانتظام لـWITS (اكتُشف حياً: HS210390 SAU->ETH).
        # هذا فارقٌ معنوي عن عطل شبكة: فجوة بيانات حقيقية لا خللاً تقنياً —
        # نص عربي هادئ بلا رابط/نص استثناء خام يتسرّب لتقرير مُنتَج.
        status = getattr(e.response, "status_code", None)
        if status is not None and 400 <= status < 500:
            note = (f"لا بيانات تعريفة مُبلَّغة إلى WITS لهذا الزوج (HS{hs6}، "
                    f"{partner_iso3}←{market_iso3}، {year}) — الزوج غير "
                    "مُغطّى في مصدر WITS لهذه السنة، ليس عطلاً تقنياً "
                    f"(HTTP {status}).")
        else:
            note = (f"WITS غير متاح الآن (HTTP {status or '؟'}) لـHS{hs6} "
                    f"{partner_iso3}←{market_iso3} {year} — أعد المحاولة لاحقاً.")
        log.warning("WITS HTTPError %s for HS%s %s->%s %s: %s",
                   status, hs6, partner_iso3, market_iso3, year, e)
        return DataPoint(None, "World Bank WITS", 0.0, note, _today())
    except Exception as e:  # noqa: BLE001 — WITS is volatile; never raise
        note = (f"WITS غير متاح الآن ({type(e).__name__}) لـHS{hs6} "
                f"{partner_iso3}←{market_iso3} {year} — أعد المحاولة لاحقاً.")
        log.warning("WITS %s for HS%s %s->%s %s: %s",
                   type(e).__name__, hs6, partner_iso3, market_iso3, year, e)
        return DataPoint(None, "World Bank WITS", 0.0, note, _today())
    if rate is None:
        note = (f"لا تعريفة مُطبَّقة قابلة للتفسير من ردّ WITS لـHS{hs6} "
                f"{partner_iso3}←{market_iso3} {year} — فجوة معلنة.")
        log.warning("WITS: no applied rate parsed for HS%s %s->%s %s",
                   hs6, partner_iso3, market_iso3, year)
        return DataPoint(None, "World Bank WITS", 0.0, note, _today())
    eu_note = (" — تعريفة الاتحاد الأوروبي الموحّدة (تشمل هذا السوق؛ "
               f"المُبلِّغ WITS: EU/918)" if is_eu else "")
    return DataPoint(
        round(rate, 2), "World Bank WITS", 0.9,
        f"reported import tariff % HS{hs6} "
        f"{partner_iso3}->{market_iso3} {year}{eu_note}", _today())


def _parse_rate(resp: requests.Response) -> float | None:
    """استخراج النسبة — pull the first tariff value from a WITS JSON or SDMX-XML reply.

    WITS may return SDMX-JSON or SDMX-ML depending on the endpoint/mood; try
    both. Returns the float rate or None if nothing parseable is found.
    """
    # المحاولة الأولى: SDMX-JSON.
    try:
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        for obs in _iter_json_obs(data):
            try:
                return float(obs)
            except (TypeError, ValueError):
                continue
        return None
    # المحاولة الثانية: SDMX-ML (XML) — Obs/@OBS_VALUE or generic ObsValue.
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        val = el.attrib.get("OBS_VALUE") or (
            el.attrib.get("value") if tag == "ObsValue" else None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _iter_json_obs(data: dict):
    """تكرار قيم الرصد — yield observation values from SDMX-JSON dataSets."""
    for ds in data.get("dataSets", []) or []:
        series = ds.get("series") or {}
        for s in series.values():
            for obs in (s.get("observations") or {}).values():
                if isinstance(obs, list) and obs:
                    yield obs[0]
        for obs in (ds.get("observations") or {}).values():
            if isinstance(obs, list) and obs:
                yield obs[0]


def tariff_with_fallback(
    hs_code: str,
    market_iso3: str,
    partner_iso3: str = "SAU",
    year: int | None = None,
) -> DataPoint:
    """التعريفة المطبَّقة عبر سلسلة تراجع — WTO TTD → WITS → فجوة معلنة.

    (الموجة: دمج مصادر جديدة) WTO TTD أولاً لأنه يسدّ فجوة التعريفة الثنائية
    المزمنة في WITS للأسواق الأوروبية (بلاغ هولندا/HS 080410 — WITS لا يعيد
    صفوف عضو الاتحاد الفردي). بلا مفتاح WTO يتدهور WTO فوراً لفجوة معلنة (لا
    نداء)، فيتولّى WITS كالسابق تماماً — توافق كامل مع السلوك القائم. كلا
    المصدرين فشلا => فجوة معلنة تحمل مصدر WITS وحالتَه (استقرار للاختبارات
    التي تؤكّد «World Bank WITS») مع ملاحظة تسمّي محاولة WTO أيضاً.

    يسجّل السطر التشخيصي أيّ مصدر خدم (`tariff path=wto/wits/gap`) — لا ادعاء
    بلا أثر (الدرس ١٠)."""
    from silk_wto_tariff import wto_applied_tariff
    wto = wto_applied_tariff(hs_code, market_iso3, partner_iso3, year)
    if wto.value is not None:
        log.info("tariff path=wto HS%s %s<-%s: %s%%",
                 _hs6(hs_code), market_iso3, partner_iso3, wto.value)
        return wto
    wits = applied_tariff(hs_code, market_iso3, partner_iso3, year)
    if wits.value is not None:
        log.info("tariff path=wits HS%s %s<-%s: %s%%",
                 _hs6(hs_code), market_iso3, partner_iso3, wits.value)
        return wits
    documented = _gcc_documented_exemption(hs_code, market_iso3, partner_iso3)
    if documented is not None:
        log.info("tariff path=gcc_agreement HS%s %s<-%s: 0.0%% (documented)",
                 _hs6(hs_code), market_iso3, partner_iso3)
        return documented
    log.info("tariff path=gap HS%s %s<-%s (WTO + WITS both unavailable)",
             _hs6(hs_code), market_iso3, partner_iso3)
    merged_note = f"{wits.note} | وWTO TTD أيضاً غير متاح: {wto.note}"
    return DataPoint(None, wits.source, 0.0, merged_note, wits.retrieved_at,
                     status=wits.status)


class TariffsAgent(BaseAgent):
    """وكيل التعريفات — applied customs tariff (%) into a market for an HS code."""

    PAID = False
    PREF_KEY = "regulatory"

    def __init__(self) -> None:
        super().__init__("TariffsAgent")

    def _execute(self, task: dict) -> AgentReport:
        """جلب التعريفة المطبّقة — fetch the applied import tariff into the market.

        task keys: hs_code, reporter_m49 or iso3 (market), partner_iso3
        (default 'SAU'), year. Failure -> failed report, never a guessed rate.
        """
        hs = task.get("hs_code")
        year = task.get("year") or _default_year()
        partner = task.get("partner_iso3", "SAU")
        iso3 = task.get("iso3") or M49_TO_ISO3.get(str(task.get("reporter_m49")))
        if not hs or not iso3:
            return AgentReport(
                self.name, [], True,
                "لا يوجد HS أو سوق صالح — missing hs_code or resolvable market ISO3")
        # سلسلة التراجع (الموجة: دمج مصادر جديدة): WTO TTD → WITS → فجوة معلنة.
        dp = tariff_with_fallback(hs, iso3, partner, year)
        failed = dp.value is None
        if failed:
            summary = "لا توجد بيانات تعريفة — no tariff data (WITS unavailable)"
        else:
            summary = f"applied tariff {dp.value}% into {iso3} from {partner} ({year})"
        return AgentReport(self.name, [dp], failed, summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk tariffs agent — best-effort WITS (degrades gracefully offline)")
    # قطن HS 5201 إلى الصين من السعودية — cotton into China from Saudi Arabia.
    report = TariffsAgent().run(
        {"hs_code": "5201", "iso3": "CHN", "partner_iso3": "SAU", "year": 2021})
    flag = "FAILED" if report.failed else "ok"
    print(f"  [{flag}] {report.agent_name}: {report.summary}")
    dp = report.findings[0]
    if dp.value is None:
        print(f"  tariff: no data / fetch failed — {dp.note}")
    else:
        print(f"  applied tariff = {dp.value}% [{dp.source}, {dp.note}]")
    _ = ISO3_TO_M49  # imported for downstream callers / symmetry.
