"""جامعا البيانات المُجدولان لسِلك — Silk budgeted data collectors (M2, §4).

يملآن مخزن الحقائق بدل الجلب اللحظي المتكرر:
  • collect_worldbank — جلب جماعي (country=all) لكل مؤشر في نداء واحد: الاقتصاد
    (سكان/دخل) + ركيزة وكيل المخاطر (حوكمة WGI، لوجستيات LPI، صرف FX). عند فشل
    الشبكة يسقط لمؤشرَي السكان/الدخل إلى اللقطة الحقيقية المضمّنة (silk_seed_data)
    بوسمها الصريح — قيم حقيقية بمصدر معلن، لا اختلاق.
  • collect_comtrade — جلب تدفقات بميزانية يومية صلبة (سجلّ collection_runs)،
    تسلسلي بإيقاع مضبوط + backoff يحترم Retry-After — عكس التوزيع المتزامن الذي
    يخنق طبقة المعاينة (ANALYSIS.md §3).
كل تشغيل يسجَّل صفاً في collection_runs (طلب/جلب/فشل/المتبقي من الميزانية).
"""
from __future__ import annotations

import datetime
import logging
import os
import time

import silk_store
from silk_data_layer import (ENDPOINTS, ISO3_TO_M49, M49_TO_ISO3,
                             COMTRADE_KEY, _comtrade_url)

log = logging.getLogger(__name__)

# مؤشرات الجلب الجماعي: الاقتصاد + ركيزة وكيل المخاطر (كلها البنك الدولي، مجانية).
WB_INDICATORS = [
    "SP.POP.TOTL",        # السكان
    "NY.GDP.PCAP.PP.CD",  # دخل الفرد PPP
    "NY.GDP.PCAP.CD",     # دخل الفرد الاسمي (بديل)
    "PV.EST",             # الاستقرار السياسي (WGI) — وكيل المخاطر
    "RQ.EST",             # جودة التنظيم (WGI) — وكيل المخاطر
    "LP.LPI.OVRL.XQ",     # مؤشر الأداء اللوجستي — وكيل المخاطر
    "PA.NUS.FCRF",        # سعر الصرف الرسمي — تقلب العملة (وكيل المخاطر)
]
_WB_CONF = 0.95


def _today_year() -> int:
    return datetime.date.today().year


def _run_start(source: str, requested: int) -> int:
    with silk_store.connect() as conn:
        cur = conn.cursor()
        cur.execute(silk_store._q(
            "INSERT INTO collection_runs (source, started_at, requested) "
            "VALUES (?,?,?)"), (source, silk_store._now(), requested))
        conn.commit()
        return cur.lastrowid


def _run_finish(run_id: int, fetched: int, failed: int,
                budget_left: int | None, note: str = "") -> None:
    with silk_store.connect() as conn:
        conn.execute(silk_store._q(
            "UPDATE collection_runs SET finished_at=?, fetched=?, failed=?, "
            "budget_left=?, note=? WHERE id=?"),
            (silk_store._now(), fetched, failed, budget_left, note, run_id))
        conn.commit()


def comtrade_budget_left() -> int:
    """المتبقي من ميزانية اليوم — daily Comtrade request budget remaining.

    السقف: COMTRADE_DAILY_BUDGET (افتراضي 450 بمفتاح، 4 بلا مفتاح — طبقة المعاينة
    عرض محدود لا مصدر إنتاج). يُحتسب المصروف من collection_runs لليوم UTC الجاري.
    """
    default = 450 if COMTRADE_KEY else 4
    cap = int(os.environ.get("COMTRADE_DAILY_BUDGET", default) or default)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    with silk_store.connect() as conn:
        row = conn.execute(silk_store._q(
            "SELECT COALESCE(SUM(fetched + failed), 0) FROM collection_runs "
            "WHERE source='comtrade' AND started_at >= ?"), (today,)).fetchone()
    spent = int(row[0] or 0)
    return max(0, cap - spent)


def collect_worldbank(indicators: list[str] | None = None,
                      year_from: int | None = None) -> dict:
    """اجلب مؤشرات البنك الدولي جماعياً — one bulk call per indicator (country=all).

    يكتب كل قيمة غير فارغة في مخزن الحقائق بمصدرها وسنتها. فشل مؤشر لا يوقف
    البقية؛ وفشل السكان/الدخل يسقط للّقطة المضمّنة الحقيقية بوسم صريح.
    Returns {fetched, failed, seeded}.
    """
    indicators = indicators or WB_INDICATORS
    year_from = year_from or (_today_year() - 6)
    run = _run_start("worldbank", len(indicators))
    fetched = failed = seeded = 0
    for ind in indicators:
        url = f"{ENDPOINTS['world_bank']}/country/all/indicator/{ind}"
        params = {"format": "json", "per_page": "20000",
                  "date": f"{year_from}:{_today_year()}"}
        try:
            import requests  # lazy — hermetic tests patch this
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            payload = r.json()
            recs = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            n = 0
            for rec in recs or []:
                iso3 = (rec.get("countryiso3code") or "").strip()
                val, yr = rec.get("value"), rec.get("date")
                if len(iso3) == 3 and val is not None and yr:
                    silk_store.upsert_indicator(
                        iso3, ind, int(yr), float(val), "World Bank", _WB_CONF,
                        f"{ind} bulk collect")
                    n += 1
            fetched += 1
            log.info("worldbank %s: %d rows", ind, n)
        except Exception as e:  # noqa: BLE001 — مؤشر يفشل، البقية تكمل
            failed += 1
            log.warning("worldbank %s failed: %s", ind, e)
            seeded += _seed_fallback(ind)
    _run_finish(run, fetched, failed, None,
                f"seeded={seeded}" if seeded else "")
    return {"fetched": fetched, "failed": failed, "seeded": seeded}


def _seed_fallback(indicator: str) -> int:
    """اللقطة الحقيقية بديلاً — real bundled snapshot rows for pop/income on failure.

    قيم حقيقية (البنك الدولي) بمصدر موسوم «لقطة مضمّنة» وسنتها الفعلية — الشبكة
    الحية تظل تفوز عند توفرها (upsert بالمصدر المنفصل). Returns rows written."""
    try:
        import silk_seed_data as seed
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    getter = None
    if indicator == "SP.POP.TOTL":
        getter = seed.population
    elif indicator.startswith("NY.GDP.PCAP"):
        getter = seed.gdp_per_capita
    if getter is None:
        return 0
    for iso3 in ISO3_TO_M49:  # الأسواق المعروفة للمنصّة تكفي كتغطية بذور
        got = getter(iso3)
        if got:
            silk_store.upsert_indicator(iso3, indicator, int(got[1]), float(got[0]),
                                        seed._SOURCE, 0.85, "seed fallback")
            n += 1
    return n


def collect_comtrade(hs6: str, targets: list[dict], year: int,
                     pace_seconds: float | None = None) -> dict:
    """اجلب تدفقات أسواقٍ بميزانية — budgeted, PACED serial Comtrade collection.

    targets: [{"iso3","m49"}...] بالأولوية. لكل هدف نداء واحد (شركاء partner=all).
    قبل كل نداء: فحص الميزانية (نفادها = توقف مُعلن لا صامت). فشل عابر يعاد
    بمحاولتين مع backoff أُسّي يحترم Retry-After. النتائج تُكتب لمخزن الحقائق.
    Returns {requested, fetched, failed, skipped_budget, budget_left}.
    """
    pace = float(os.environ.get("COMTRADE_PACE_S", "1.0")
                 if pace_seconds is None else pace_seconds)
    run = _run_start("comtrade", len(targets))
    fetched = failed = skipped = 0
    from silk_data_layer import comtrade_trade, primary_value
    # الميزانية تُقرأ مرة وتُخصم محلياً داخل التشغيلة (صف collection_runs يُحدَّث
    # عند النهاية فقط) — read once, decrement locally within the run.
    budget = comtrade_budget_left()
    # مراجعة المشروع: الميزانية تُحاسِب **النداءات الفعلية** لا الأهداف —
    # حلقة الإعادة كانت تطلق حتى ٣ نداءات وتُحتسب هدفاً واحداً، فيتجاوز
    # الصرف الحقيقي السقف اليومي. `calls` = كل استدعاء comtrade_trade؛
    # ودفتر collection_runs يبقى صادقاً لأن failed صار "محاولات فاشلة"
    # (calls - نجاحات) فيساوي SUM(fetched+failed) مجموعَ النداءات الفعلية.
    # حدّ معروف: [] لا يميّز "فشل جلب" عن "سوق لا يستورد فعلاً" (عقد
    # comtrade_trade) — فالإعادة قد تكرّر سؤالاً جوابه الصادق فارغ.
    calls = 0
    failed_targets = 0
    for t in targets:
        if calls >= budget:
            skipped = len(targets) - fetched - failed_targets
            log.warning("comtrade budget exhausted — %d target(s) deferred", skipped)
            break
        ok = False
        for attempt in range(3):  # محاولة + إعادتان بتراجع أُسّي
            recs = comtrade_trade(hs6, t["m49"], year,
                                  flow="M", partner="all") or []
            calls += 1
            if recs:
                rows = []
                for rec in recs:
                    code = str(rec.get("partnerCode"))
                    val = primary_value(rec)
                    if val is None:
                        continue
                    piso = "WLD" if code == "0" else M49_TO_ISO3.get(code, code)
                    rows.append({"hs6": hs6, "reporter_iso3": t["iso3"],
                                 "partner_iso3": piso, "year": int(year),
                                 "flow": "M", "value_usd": val})
                if rows:
                    silk_store.upsert_trade_flows(rows)
                ok = True
                break
            if calls >= budget:  # لا محاولة إضافية فوق الميزانية
                break
            time.sleep(pace * (2 ** attempt))  # backoff — طبقة المعاينة حسّاسة للاندفاع
        if ok:
            fetched += 1
        else:
            failed_targets += 1
        time.sleep(pace)  # إيقاع بين الأهداف — pacing between targets
    failed = calls - fetched   # محاولات فاشلة — keeps the daily ledger honest
    left = comtrade_budget_left()
    _run_finish(run, fetched, failed, left,
                f"skipped_budget={skipped}" if skipped else "")
    return {"requested": len(targets), "fetched": fetched, "failed": failed,
            "skipped_budget": skipped, "budget_left": left}


def _priority_targets() -> list[dict]:
    """أسواق الأولوية للتسخين المسبق — priority markets for pre-warming.

    من `SILK_PRIORITY_MARKETS` (رموز ISO3 مفصولة بفواصل) إن ضُبط، وإلا أول
    أسواق قائمة المنصّة (الخليج + الجوار — الأكثر طلباً). رموز غير معروفة
    تُتجاهل — لا اختلاق سوق. Env-driven list, else the platform's top markets.
    """
    from silk_market_ranker import COUNTRIES
    raw = os.environ.get("SILK_PRIORITY_MARKETS", "").strip()
    if raw:
        by = {c["iso3"]: c for c in COUNTRIES}
        wanted = [s.strip().upper() for s in raw.split(",") if s.strip()]
        return [{"iso3": w, "m49": by[w]["m49"]} for w in wanted if w in by]
    return [dict(c) for c in COUNTRIES[:12]]


def _recent_hs_codes(limit: int = 8) -> list[str]:
    """رموز HS المطلوبة مؤخراً — recently analyzed HS codes, newest first.

    من سجل التحليلات (silk_storage — الأحدث أولاً)؛ فشل القراءة = قائمة فارغة
    (التحديث تحسين لا شرط). Reads the analyses log; empty on any failure.
    """
    out: list[str] = []
    seen: set[str] = set()
    try:
        import silk_storage
        for row in silk_storage.list_analyses():
            hs = (row.get("hs_code") or "").strip()
            if hs and hs not in seen:
                seen.add(hs)
                out.append(hs)
            if len(out) >= limit:
                break
    except Exception as e:  # noqa: BLE001 — سجل غائب/تالف لا يوقف التحديث
        log.debug("recent-hs read skipped: %s", e)
    return out


def refresh() -> dict:
    """التحديث المُجدول — the worker entrypoint.

    ١) مؤشرات البنك الدولي جماعياً (مجاني).
    ٢) تسخين مسبق لتدفقات Comtrade: رموز HS المطلوبة مؤخراً × أسواق الأولوية،
       للسنة المغلقة الأخيرة — عبر collect_comtrade نفسه (ميزانية يومية صلبة،
       إيقاع + backoff يحترم Retry-After؛ لا اندفاع على المصادر أبداً). يُترك
       احتياطي ميزانية للطلبات الحية (`SILK_REFRESH_BUDGET_RESERVE`، افتراضي
       150 نداء) — التسخين لا يجوّع تحليلات المستخدمين.
    التحليل الحي التالي لنفس hs+سوق+سنة يُخدم من المخزن بصفر نداء مدفوع.
    Pre-warms recent HS × priority markets within the existing hard budget.
    """
    silk_store.migrate()
    wb = collect_worldbank()
    reserve = int(os.environ.get("SILK_REFRESH_BUDGET_RESERVE", "150") or 150)
    year = _today_year() - 1  # السنة المغلقة الأخيرة — بيانات سنوية مستقرة
    targets = _priority_targets()
    comtrade_runs: list[dict] = []
    for hs in _recent_hs_codes():
        left = comtrade_budget_left()
        if left <= reserve:
            log.info("refresh: stopping pre-warm — budget reserve reached "
                     "(%d left ≤ %d reserve)", left, reserve)
            break
        got = collect_comtrade(hs, targets, year)
        comtrade_runs.append({"hs6": hs, "year": year, **got})
    # مراقبة ما بعد الدخول (الموجة ٤) — نفس الخيط والإيقاع (SILK_REFRESH_HOURS)،
    # لا خدمة cron منفصلة (قرص Railway يُركَّب على خدمة واحدة فقط). فشلها لا
    # يُسقط بقية التحديث الدوري — تحذير مسجَّل فقط.
    try:
        alerts = check_post_entry()
    except Exception as e:  # noqa: BLE001 — طبقة مراقبة لا تُسقط التحديث
        log.warning("post-entry monitoring skipped: %s", e)
        alerts = []
    return {"worldbank": wb, "comtrade": comtrade_runs,
            "comtrade_budget_left": comtrade_budget_left(),
            "post_entry_alerts": alerts}


# ── مراقبة ما بعد الدخول (الموجة ٤، V5) ──────────────────────────────────────
# لتحليلات البحث العميق (result["deep_research"]) المُعلَّمة outcome="entered"
# فقط — تعيد جلب إشارتَي trade_flow/risk_news حيّاً وتقارن بما خزَّنته البعثتان
# أصلاً؛ تغيّر جوهري (نمو استيراد سلبي حالياً / تعريفة تغيّرت) = تنبيه مُسجَّل
# يظهر في اللوحة (view["deep_research"], لاحقاً). لا استدعاء كلود هنا إطلاقاً —
# نفس انضباط هذا الملف بأكمله (بيانات حتمية فقط)؛ فحص «الإشارة» لا إعادة تشغيل
# البعثة بأكملها.

def _entered_deep_research_analyses(path: str | None = None) -> list[dict]:
    """التحليلات المُدخَلة فعلياً وذات بحث عميق — outcome=entered فقط."""
    import silk_storage
    out = []
    for meta in silk_storage.list_analyses(path):
        if meta.get("outcome") != "entered":
            continue
        full = silk_storage.get_analysis(meta["id"], path)
        if not full or not full.get("deep_research"):
            continue
        out.append({"id": meta["id"], "full": full})
    return out


def _stored_tariff_pct(full: dict) -> float | None:
    """التعريفة المخزَّنة أصلاً من بعثة tariffs_agreements — تحليل نصّي محافظ."""
    import re
    mission = ((full.get("deep_research") or {}).get("missions") or {}).get(
        "tariffs_agreements") or {}
    for f in mission.get("findings") or []:
        note = str(f.get("note") or "") + " " + str(f.get("value") or "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", note)
        if m:
            return float(m.group(1))
    return None


def check_post_entry(path: str | None = None) -> list[dict]:
    """راقب التحليلات المُدخَلة — إشارة تجارة+مخاطر حيّة لكل واحدة، وتنبيه
    عند تغيّر جوهري. تعيد قائمة التنبيهات (وتُسجّلها warning)؛ فشل جلب
    تحليل واحد لا يوقف البقية (نفس مبدأ عزل الأعطال القائم في هذا الملف)."""
    from silk_data_layer import comtrade_trade, primary_value
    from silk_tariffs_agent import applied_tariff

    alerts: list[dict] = []
    year = _today_year() - 1
    for item in _entered_deep_research_analyses(path):
        aid, full = item["id"], item["full"]
        hs = full.get("hs_code")
        market = full.get("market") or {}
        iso3, m49 = market.get("iso3"), market.get("m49")
        if not hs or not iso3:
            continue
        try:
            cur = comtrade_trade(hs, m49 or iso3, year, flow="M", partner=0)
            prev = comtrade_trade(hs, m49 or iso3, year - 1, flow="M", partner=0)
        except Exception as e:  # noqa: BLE001 — عزل الأعطال، لا سقوط جماعي
            log.warning("post-entry monitoring: trade fetch failed for "
                       "analysis %s: %s", aid, e)
            continue
        cur_v = sum(v for v in (primary_value(r) for r in (cur or [])) if v)
        prev_v = sum(v for v in (primary_value(r) for r in (prev or [])) if v)
        growth_negative = bool(prev_v) and cur_v < prev_v

        tariff_changed = False
        new_tariff = None
        stored_tariff = _stored_tariff_pct(full)
        if stored_tariff is not None:
            dp = applied_tariff(hs, iso3, year=year)
            if dp.value is not None:
                new_tariff = dp.value
                tariff_changed = abs(dp.value - stored_tariff) >= 1.0  # نقطة مئوية

        if not growth_negative and not tariff_changed:
            continue
        alert = {
            "analysis_id": aid, "hs_code": hs, "iso3": iso3,
            "growth_negative": growth_negative,
            "tariff_changed": tariff_changed,
            "old_tariff_pct": stored_tariff, "new_tariff_pct": new_tariff,
            "checked_at": datetime.date.today().isoformat(),
        }
        alerts.append(alert)
        log.warning("post-entry alert (analysis %s, HS%s->%s): %s",
                   aid, hs, iso3, alert)
    return alerts


# ── المُجدول داخل العملية · in-process scheduler ─────────────────────────────
# قرص Railway الدائم يُركَّب على خدمة واحدة فقط — خدمة cron منفصلة لا ترى
# `/data` نفسه، فيتغذّى مخزنٌ لا يقرأه أحد. لذا يعمل التحديث الدوري خيطاً
# خلفياً داخل خدمة الويب نفسها (نفس القرص، نفس الميزانية).
# A Railway volume mounts to ONE service, so a separate cron service could
# not share /data; the periodic refresh runs as a daemon thread in-process.

_scheduler_started = False


def start_scheduler():
    """ابدأ التحديث الدوري — start the periodic refresh thread (idempotent).

    يُفعَّل بـ `SILK_REFRESH_HOURS` (عدد ساعات بين التشغيلات؛ غير مضبوط/0 =
    معطّل — لا خيط إطلاقاً، فالاختبارات والتطوير لا تتأثر). أول تشغيلة بعد
    `SILK_REFRESH_INITIAL_S` (افتراضي 120ث) كي لا يزاحم الإقلاع. فشل تشغيلة
    يُسجَّل ولا يقتل الخيط. Returns the Thread, or None when disabled.
    """
    global _scheduler_started
    try:
        hours = float(os.environ.get("SILK_REFRESH_HOURS", "0") or 0)
    except ValueError:
        log.warning("SILK_REFRESH_HOURS is not a number — scheduler disabled")
        return None
    if hours <= 0 or _scheduler_started:
        return None

    import threading

    initial = float(os.environ.get("SILK_REFRESH_INITIAL_S", "120") or 120)

    def _loop() -> None:
        delay = initial
        while True:
            time.sleep(delay)
            # حصاد التشغيلات اليتيمة دورياً (فوق حصاد الإقلاع) — يلتقط تعطّلاً
            # حدث أثناء حياة العملية لا عند إعادة النشر فقط. مستقل عن refresh:
            # فشل أحدهما لا يمنع الآخر (الخيط يبقى في كل الأحوال).
            try:
                import silk_storage
                reaped = silk_storage.reap_orphan_research_runs()
                if reaped:
                    log.warning("periodic orphan reaper marked %d stale runs "
                                "failed: %s", len(reaped), reaped)
            except Exception as e:  # noqa: BLE001 — الحصاد يفشل، الخيط يبقى
                log.warning("periodic orphan reaper failed: %s", e)
            try:
                got = refresh()
                log.info("scheduled refresh done: %s", got)
            except Exception as e:  # noqa: BLE001 — تشغيلة تفشل، الخيط يبقى
                log.warning("scheduled refresh failed: %s", e)
            delay = hours * 3600

    t = threading.Thread(target=_loop, daemon=True, name="silk-refresh")
    t.start()
    _scheduler_started = True
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("silk_collectors —", refresh())
