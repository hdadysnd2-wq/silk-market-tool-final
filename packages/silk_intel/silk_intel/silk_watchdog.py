"""الحارس — Silk platform watchdog ("كاميرا مراقبة" داخل المنصّة).

أداةٌ **مملوكة للمالك حصراً** (LAW — تسلسل القيادة): تراقب كل تشغيلة
(`/analyze` و`/research` معاً، عبر نقطة الاختناق المشتركة في `api.py`)
وتُنتج سجلَّ صحّةٍ حتمياً — صفر نداء كلود إضافي، صفر تعديل على نتيجة
التشغيلة. الحارس **لا يمنع ولا يبطئ** أي تشغيلة أبداً؛ كل خطأ فيه يذهب
لسجلّ العمليات (`silk_ops_log`) لا للمستخدم ولا يُسقِط التحليل — راجع
`observe()`.

**مبدأ عدم التلوّث (LESSON الجديد):** لا سطرَ حارسٍ واحد يصل أي سطح عميل
(`web/index.html` تعرض «تقرير الحارس» في مدخلٍ منفصلٍ تماماً عن أي تحليل؛
`silk_render`/`silk_reports` لا يستوردان هذه الوحدة إطلاقاً) — نفس مبدأ
عزل أسماء المزوّدين (`_CLIENT_VENDOR_NAMES`, اللائحة الدرس ١٨).

يُخزَّن في قاعدة بيانات **مستقلة تماماً عن silk.db** (نفس فلسفة
`silk_ops_log`/`silk_usage`) — `watchdog.db` تحت نفس توجيه `SILK_DATA_DIR`.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3

log = logging.getLogger(__name__)

GREEN, YELLOW, RED = "green", "yellow", "red"
_SEVERITY_RANK = {GREEN: 0, YELLOW: 1, RED: 2}

# الخدمات الثلاث المعروفة حياً (البلاغ الحي + عائلة C، الدرس ٢٦) — عدا هذه
# الثلاث، أي `service_failure` جديد في السجل يظهر أيضاً (لا قائمة مقفلة).
_KNOWN_SERVICES_AR = {
    "scraper": "المكشطة",
    "trends": "اتجاهات البحث",
    "imf": "صندوق النقد الدولي",
}

# عدد بنود التدقيق المفتوحة المعروفة (H-1..H-9، PR #134 — Wave 4 خارج
# نطاق هذا الحارس، تُذكَر فقط كي يعرف القارئ ما يُراقَب وما هو معروفٌ
# ومفتوحٌ أصلاً بلا رصدٍ آلي بعد). ثابتٌ توثيقيٌّ لا قاعدةُ منتجٍ مكتوبة صلباً.
KNOWN_OPEN_BACKLOG_COUNT = 9
KNOWN_OPEN_BACKLOG_NOTE = (
    "٩ بنود تدقيق مفتوحة (H-1..H-9) من التدقيق الشامل السابق — خارج نطاق "
    "رصد الحارس الآلي حالياً، مسجّلة في docs/DECISIONS.md")


# ── تخزين — قاعدة بيانات مستقلة (نمط silk_ops_log.py) ───────────────────────

_DEFAULT_PATH = os.path.join("data", "watchdog.db")


def _db_path() -> str:
    explicit = os.environ.get("SILK_WATCHDOG_DB", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("SILK_DATA_DIR", "").strip()
    if base:
        return os.path.join(base, "watchdog.db")
    return _DEFAULT_PATH


def _connect(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watchdog_records ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, "
        "kind TEXT NOT NULL, product TEXT, market TEXT, overall TEXT NOT NULL, "
        "created_at TEXT NOT NULL, record_json TEXT NOT NULL)")
    return conn


def _store(record: dict, path: str | None = None) -> int | None:
    """خزّن سجلّ صحّةٍ واحداً — قناة جانبية صامتة (فشل الكتابة لا يكسر شيئاً)."""
    path = path or _db_path()
    try:
        with _connect(path) as conn:
            cur = conn.execute(
                "INSERT INTO watchdog_records (analysis_id, kind, product, "
                "market, overall, created_at, record_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.get("analysis_id"), record.get("kind"),
                 record.get("product"), record.get("market"),
                 record.get("overall"), record.get("created_at"),
                 json.dumps(record, ensure_ascii=False, default=str)))
            cap = int(os.environ.get("SILK_WATCHDOG_CAP", "") or 2000)
            conn.execute(
                "DELETE FROM watchdog_records WHERE id NOT IN "
                "(SELECT id FROM watchdog_records ORDER BY id DESC LIMIT ?)",
                (max(1, cap),))
            return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001 — تخزين تشخيصي، لا يكسر التحليل أبداً
        log.warning("watchdog record write failed: %s", e)
        return None


def list_records(n: int = 50, path: str | None = None) -> list[dict]:
    """آخر `n` سجلّ صحّة (الأحدث أولاً) — `[]` بلا قاعدة/صفوف، لا استثناء."""
    path = path or _db_path()
    if not os.path.exists(path):
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT record_json FROM watchdog_records "
                "ORDER BY id DESC LIMIT ?", (max(1, int(n)),)).fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["record_json"]))
            except Exception:  # noqa: BLE001 — صفّ فاسد يُهمَل لا يكسر القراءة
                continue
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("watchdog record read failed: %s", e)
        return []


def get_record(watchdog_id: int, path: str | None = None) -> dict | None:
    path = path or _db_path()
    if not os.path.exists(path):
        return None
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT record_json FROM watchdog_records WHERE id = ?",
                (watchdog_id,)).fetchone()
        return json.loads(row["record_json"]) if row else None
    except Exception as e:  # noqa: BLE001
        log.warning("watchdog record fetch failed (id=%s): %s", watchdog_id, e)
        return None


def record_blocked_export(analysis_id: int | None, product: str | None,
                          market: str | None, gate_findings: list[dict],
                          fmt: str) -> dict | None:
    """سجلّ حدثاً مستقلاً حين تُحجَب تصدير عميل بسبب FAIL في بوابة الجودة
    (§0 — الفكس الجذري: البوابة كانت «تحسين لا شرط تسليم»). سجلٌّ منفصلٌ
    عن `observe()` الخاص بالتشغيلة نفسها (`kind="export_blocked"` لا
    `"research"`) كي يميّز الحارس بين «شُحن» و«حُجب» بدل خلطهما."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    record = {
        "analysis_id": analysis_id, "kind": "export_blocked",
        "product": product, "market": market, "overall": RED,
        "created_at": now, "contracts": {}, "economics": {},
        "services": [], "failures": {},
        "findings": [_finding(
            "client_export_blocked", RED,
            f"تصدير العميل ({fmt}) حُجب: بوابة الجودة FAIL "
            f"({len(gate_findings or [])} ملاحظة).", "export_gate")],
        "self_error": None,
    }
    _store(record)
    return record


def record_override(analysis_id: int | None, product: str | None,
                    market: str | None, gate_findings: list[dict],
                    fmt: str) -> dict | None:
    """WP-7 §1 — كل تجاوز مالكٍ لبوابة الجودة (`?override=1` بسلطة
    `SILK_OWNER_KEY` المنفصلة) يُسجَّل حدثاً مستقلاً `kind="export_override"`
    — يقرؤه التصدير الداخلي (`?internal=1`) ليختم النسخة التشغيلية بسطر
    «سُلِّم بتجاوز مالك — ملاحظات البوابة مرفقة»."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    record = {
        "analysis_id": analysis_id, "kind": "export_override",
        "product": product, "market": market, "overall": RED,
        "created_at": now, "contracts": {}, "economics": {},
        "services": [], "failures": {},
        "findings": [_finding(
            "client_export_override", RED,
            f"تصدير العميل ({fmt}) سُلِّم بتجاوز مالكٍ رغم FAIL بوابة "
            f"الجودة ({len(gate_findings or [])} ملاحظة).", "export_gate")],
        "gate_findings": [
            {"check": f.get("check"), "note": f.get("note")}
            for f in (gate_findings or [])][:12],
        "self_error": None,
    }
    _store(record)
    return record


def override_records_for(analysis_id: int | None,
                         path: str | None = None) -> list[dict]:
    """سجلّات تجاوز المالك لتحليل بعينه (الأحدث أولاً) — `[]` بلا قاعدة/صفوف."""
    if analysis_id is None:
        return []
    path = path or _db_path()
    if not os.path.exists(path):
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT record_json FROM watchdog_records WHERE "
                "kind = 'export_override' AND analysis_id = ? "
                "ORDER BY id DESC", (int(analysis_id),)).fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["record_json"]))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("watchdog override read failed: %s", e)
        return []


# ── PART 1 — طبقة الاستشعار: حساب حتمي، صفر نداء كلود ───────────────────────

_VENDOR_PLACEHOLDER_RE = re.compile(r"\[شعار[^\]]*\]|\[LOGO[^\]]*\]", re.I)
_SECTION_GLYPH_RE = re.compile(r"§")


def _finding(code: str, severity: str, message_ar: str, check: str = "") -> dict:
    return {"code": code, "severity": severity, "message_ar": message_ar,
            "check": check or code}


def _check_hs_gate(result: dict) -> tuple[dict, list[dict]]:
    """بوّابة HS — الرمز مؤكَّد، أو تجاوَزه المستخدم صراحةً (يُعلَن)، أو
    (لا يجب أن يحدث والحارس مفعَّل) مرّ غير مؤكَّد بلا تجاوز — خرقٌ يُبلَّغ
    أحمر بدل أن يكتشفه المالك في تقرير مدفوع (نفس عائلة اللائحة ٣٥)."""
    conf = result.get("hs_confirmation")
    if not isinstance(conf, dict):
        return {"status": "n/a", "detail": "لا رمز HS معلَّم لهذه التشغيلة"}, []
    if conf.get("confirmed") is not False:
        return {"status": "confirmed", "detail": "رمز HS مؤكَّد"}, []
    # confirmed is False ووصلنا لهنا (تشغيلة اكتملت) => إما تجاوزٌ صريح من
    # المستخدم أو أن البوّابة كانت مُطفأة. لا نملك هنا علماً يميّز الحالتين
    # بيقين (hs_confirmed لا يُخزَّن في النتيجة) فنُبلِغ الحالة الأخفّ
    # (تجاوزٌ محتمل) — لا اختلاق يقين لا دليل عليه.
    from silk_hs_confirm import gate_enabled
    if gate_enabled():
        return {"status": "overridden",
                "detail": f"رمز HS {conf.get('hs_code')} غير مؤكَّد؛ "
                          "التشغيلة تابعت بتأكيدٍ صريح من المستخدم"}, [
            _finding("hs_gate_overridden", YELLOW,
                     f"رمز HS {conf.get('hs_code')} («{conf.get('code_desc')}») "
                     "غير مؤكَّد — تابعت التشغيلة بتأكيدٍ صريح من المستخدم؛ "
                     "أرقامها المشتقّة مؤشرات سياقية لا مقياس فعلي.",
                     "hs_gate")]
    return {"status": "unconfirmed_unsafe",
            "detail": f"رمز HS {conf.get('hs_code')} غير مؤكَّد ومرّ بلا "
                      "بوّابة (البوّابة مُطفأة)"}, [
        _finding("hs_gate_unsafe", RED,
                 f"رمز HS {conf.get('hs_code')} («{conf.get('code_desc')}») "
                 "غير مؤكَّد ومضت التشغيلة بلا بوّابة (SILK_HS_CONFIRM_GATE "
                 "مُطفأة صراحةً) — خرق عقد عدم الإنفاق الصامت.",
                 "hs_gate")]


_BADGE_CLASS_KEYWORDS = (
    ("conditional", ("دخول مشروط",)),
    ("go", ("التوصية بالدخول",)),
    ("nogo", ("عدم الدخول",)),
    ("watch", ("مراقبة",)),
)


def _badge_class(text: str) -> str | None:
    for cls, kws in _BADGE_CLASS_KEYWORDS:
        if any(kw in (text or "") for kw in kws):
            return cls
    return None


def _check_badge_body(dr: dict) -> tuple[dict, list[dict]]:
    """شارة الحكم (verdict_label) يجب أن تطابق تصنيف المتن (اللائحة ٣٢، ١.١)
    — تحقّقٌ مستقلٌّ (شبكة أمان) لا يعتمد على أن الشارة والمتن اشتُقّا فعلاً
    من نفس المصدر داخلياً، إذ كلاهما تنفيذان متوازيان قابلان للانحراف."""
    if not dr:
        return {"status": "n/a", "detail": ""}, []
    badge = dr.get("verdict_label") or ""
    verdict = dr.get("verdict") or {}
    try:
        # مراجعة شيفرة PR #147: نفس المصدر الواحد للحكم (الحتمي أولاً) الذي
        # تُشتقّ منه الشارة — القراءة القديمة (ai أولاً) كانت ستُطلق
        # badge_body_mismatch كاذباً كلما خالفت قراءةُ كلود الحكمَ الحتمي.
        from silk_narrative import authoritative_verdict, verdict_ar
        v_raw, _ = authoritative_verdict(verdict)
        body = verdict_ar(v_raw or "")
    except Exception:  # noqa: BLE001 — فحصٌ إضافي، لا يكسر الحارس
        return {"status": "n/a", "detail": ""}, []
    bc, tc = _badge_class(badge), _badge_class(body)
    if bc is None or tc is None or bc == tc:
        return {"status": "match", "detail": f"{badge} == {body}"}, []
    return {"status": "mismatch", "detail": f"شارة «{badge}» ≠ متن «{body}»"}, [
        _finding("badge_body_mismatch", RED,
                 f"شارة الحكم «{badge}» لا تطابق تصنيف المتن «{body}» — "
                 "تناقضٌ على الصفحة الأولى.", "badge_body")]


def _check_cross_market_leak(analysis_id: int | None, market_iso3: str | None
                             ) -> tuple[dict, list[dict]]:
    """صفر حقيقة مختومة لسوقٍ آخر في نقاط تفتيش هذه التشغيلة (اللائحة ٣٦) —
    قراءة مباشرة من `research_missions`، لا تحليل نصّ. لا تُطبَّق إلا على
    تشغيلات `/research` محفوظة (analysis_id) بسوقٍ معروف."""
    if not analysis_id or not market_iso3:
        return {"status": "n/a", "detail": "تشغيلة غير محفوظة أو بلا سوق محدَّد"}, []
    try:
        from silk_storage import checkpoint_market_iso3s
        seen = checkpoint_market_iso3s(analysis_id)
    except Exception as e:  # noqa: BLE001
        return {"status": "n/a", "detail": f"تعذّر الفحص: {e}"}, []
    foreign = seen - {market_iso3}
    if not foreign:
        return {"status": "clean", "detail": "لا أسواق أخرى مختومة"}, []
    return {"status": "violation",
            "detail": f"أسواق أجنبية مختومة: {sorted(foreign)}"}, [
        _finding("cross_market_leak", RED,
                 f"تسرّب بيانات عبر-سوقي: نقاط تفتيش مختومة بسوقٍ آخر "
                 f"({'، '.join(sorted(foreign))}) وُجدت ضمن تشغيلة سوق "
                 f"{market_iso3} — خرق سرّية/صحة.", "cross_market")]


def _check_leaks(dr: dict) -> tuple[dict, list[dict]]:
    """تسريب مزوّد/§/نائب **ناجٍ من مسار التطهير الحقيقي** — يعيد استعمال
    حارس تصدير العميل القائم بنفس تسلسله (`_client_sanitize` ثم
    `_client_forbidden_hits`، تماماً كـ`_client_assert_clean`) بدل فحص
    النصّ الخام قبل التطهير (اللائحة ١٨) — النصّ الخام في `view` يحمل عمداً
    لغةً تشغيلية («بعثة»/«تشغيلة») تُنقَّى فقط عند التصدير الفعلي؛ فحصها
    خاماً يُنتج تحذيراً كاذباً دائماً بلا قيمة."""
    if not dr:
        return {"status": "n/a", "detail": ""}, []
    text = ((dr.get("report") or {}).get("text") or "")
    summaries = " ".join(str((m or {}).get("summary") or "")
                         for m in (dr.get("missions") or {}).values())
    blob = text + "\n" + summaries
    if not blob.strip():
        return {"status": "n/a", "detail": "لا نصّ تقرير"}, []
    hits: list[str] = []
    sanitized = blob
    try:
        from silk_reports import _client_forbidden_hits, _client_sanitize
        sanitized = _client_sanitize(blob)
        hits.extend(_client_forbidden_hits(sanitized))
    except Exception as e:  # noqa: BLE001
        log.warning("watchdog vendor-leak reuse failed: %s", e)
    if _SECTION_GLYPH_RE.search(sanitized):
        hits.append("section_glyph: «§»")
    if _VENDOR_PLACEHOLDER_RE.search(sanitized):
        hits.append("unresolved_placeholder")
    if not hits:
        return {"status": "clean", "detail": ""}, []
    return {"status": "leak", "detail": "؛ ".join(hits[:5])}, [
        _finding("vendor_section_placeholder_leak", RED,
                 f"تسريب سباكة/مزوّد/نائب في نصّ التقرير: {'؛ '.join(hits[:3])}",
                 "leaks")]


def _check_stale_tags(dr: dict) -> tuple[dict, list[dict]]:
    """تحقّقٌ مستقلٌّ لوسم «الأحدث المتاح» فوق كل سنة حقيقة متقادِمة معروفة
    (اللائحة ٣٣) — إعادة حساب سنوات التقادُم من الحقول البنيوية ثم فحص
    ورودها في المتن بلا وسمٍ مجاور."""
    if not dr:
        return {"status": "n/a", "detail": ""}, []
    text = ((dr.get("report") or {}).get("text") or "")
    if not text:
        return {"status": "n/a", "detail": "لا نصّ تقرير"}, []
    try:
        from silk_staleness import stale_fact_years
        missions = dr.get("missions") or {}
        all_findings = [f for v in missions.values() for f in (v.get("findings") or [])]
        years = stale_fact_years(all_findings)
    except Exception as e:  # noqa: BLE001
        return {"status": "n/a", "detail": f"تعذّر الحساب: {e}"}, []
    if not years:
        return {"status": "n/a", "detail": "لا حقائق متقادِمة"}, []
    untagged = []
    for yr in sorted(years):
        for m in re.finditer(rf"(?<![\d/]){int(yr)}(?![\d/])", text):
            window = text[max(0, m.start() - 40):m.end() + 40]
            if "الأحدث المتاح" not in window:
                untagged.append(int(yr))
                break
    if not untagged:
        return {"status": "ok", "detail": f"سنوات متقادِمة موسومة: {sorted(years)}"}, []
    return {"status": "flagged", "detail": f"سنوات بلا وسم: {untagged}"}, [
        _finding("stale_tag_missing", YELLOW,
                 f"سنة/سنوات بيانات متقادِمة ({untagged}) وردت في المتن بلا "
                 "وسم «الأحدث المتاح» مجاور.", "stale_tags")]


_RETAIL_NOTE_RE = re.compile(r"تجزئة")
_WHOLESALE_NOTE_RE = re.compile(r"متوسط سعر الاستيراد")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numeric(v: object) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        m = _NUM_RE.search(v)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _check_price_sanity(dr: dict) -> tuple[dict, list[dict]]:
    """سعر تجزئة أدنى بوضوح من متوسط سعر الاستيراد (جملة) — تناقضٌ صريح
    (اللائحة/البند ١.٣: 0.67$ تجزئة مقابل 6$ جملة) يُبلَّغ لا يُصحَّح صامتاً."""
    if not dr:
        return {"status": "n/a", "detail": ""}, []
    findings = ((dr.get("missions") or {}).get("pricing_scout") or {}).get("findings") or []
    retail = wholesale = None
    for f in findings:
        note = str((f or {}).get("note") or "")
        val = _numeric((f or {}).get("value"))
        if val is None:
            continue
        if retail is None and _RETAIL_NOTE_RE.search(note):
            retail = val
        elif wholesale is None and _WHOLESALE_NOTE_RE.search(note):
            wholesale = val
    if retail is None or wholesale is None or wholesale <= 0:
        return {"status": "n/a", "detail": "لا زوج تجزئة/جملة قابل للمقارنة"}, []
    if retail < wholesale:
        return {"status": "flagged",
                "detail": f"تجزئة {retail} < جملة {wholesale}"}, [
            _finding("price_sanity", YELLOW,
                     f"سعر التجزئة المرصود ({retail}) أقلّ من متوسط سعر "
                     f"الاستيراد بالجملة ({wholesale}) — تناقضٌ يحتاج تفسيراً "
                     "صريحاً في التقرير (غالباً فئة HS مجاورة).",
                     "price_sanity")]
    return {"status": "ok", "detail": f"تجزئة {retail} >= جملة {wholesale}"}, []


def _check_no_fabrication(dr: dict) -> tuple[dict, list[dict]]:
    """عقد عدم الاختلاق: لا `DataPoint` تحمل قيمةً غير فارغة مع ثقةٍ 0.0 —
    زوجٌ متناقض (إما ثقةٌ حقيقية أو فجوة None/0.0 كاملة، لا مزيج)."""
    if not dr:
        return {"status": "n/a", "detail": ""}, []
    bad = []
    for key, m in (dr.get("missions") or {}).items():
        for f in (m.get("findings") or []):
            val = (f or {}).get("value")
            conf = (f or {}).get("confidence")
            if conf == 0.0 and val not in (None, "", [], {}):
                bad.append(key)
    if not bad:
        return {"status": "held", "detail": ""}, []
    return {"status": "violation", "detail": f"بعثات: {sorted(set(bad))}"}, [
        _finding("fabrication_contract_violation", RED,
                 f"قيمةٌ غير فارغة بثقة 0.0 في بعثة/بعثات {sorted(set(bad))} — "
                 "خرق عقد عدم الاختلاق (يجب None بثقة 0.0 أو قيمة موثوقة، لا مزيج).",
                 "no_fabrication")]


def _tariff_path(dr: dict) -> str | None:
    """مصدر سطر التعريفة (wto/wits/gap) — من حقل `source` للنقطة نفسها، لا
    تحليل سجلّات (`silk_tariffs_agent.tariff_with_fallback`)."""
    findings = ((dr or {}).get("missions") or {}).get("tariffs_agreements", {}).get("findings") or []
    for f in findings:
        src = str((f or {}).get("source") or "")
        if src == "WTO TTD":
            return "wto"
        if src == "World Bank WITS":
            return "wits" if (f or {}).get("value") is not None else "gap"
    return None


_SERVICE_FINDING_AR = {
    "scraper": "الكاشط رفض المهمة أو فشل الاتصال — جدول المستوردين قد يكون "
              "جاء من المسار الاحتياطي (خرائط قوقل) أو فجوة معلنة.",
    "trends": "اتجاهات البحث رفضت الطلب (على الأرجح حدّ معدّل 429) — إشارة "
             "الموسمية/الاهتمام فجوة معلنة أو موسّعة لفئة أعمّ.",
    "imf": "مؤشر صندوق النقد الدولي فشل جزئياً لمؤشرٍ واحد أو أكثر — "
          "القيمة فجوة معلنة، لا اختلاق.",
}


def _check_services(duration_s: float | None,
                    n_last: int = 60) -> tuple[list[dict], list[dict]]:
    """أعطال خدمات خارجية وقعت **خلال نافذة زمن التشغيلة** — قراءة تقريبية
    من `silk_ops_log` (لا وسم analysis_id على صفوف service_failure اليوم،
    فالمطابقة زمنية تقريبية بديلاً معقولاً بلا نداء إضافي أو تعديل مخازن
    أخرى). النافذة = [الآن − (مدّة التشغيلة + هامش)، الآن]. مُفصَّح كتقريب
    لا يقين — تشغيلاتٌ متزامنة (أو نشاطٌ آخر يكتب لنفس السجلّ المشترك خلال
    النافذة) قد تتشارك سطراً. **مجمَّعٌ بخدمةٍ واحدة** — عدّة أعطالٍ لنفس
    الخدمة ضمن التشغيلة تُبلَّغ بندًا واحدًا لا قائمةً مكرَّرة (خدمةٌ واحدة
    فشلت ٥ مرّات تبقى ملاحظةً واحدة، لا خمس)."""
    try:
        import silk_ops_log
        rows = silk_ops_log.last_errors(n_last)
    except Exception as e:  # noqa: BLE001
        return [], [_finding("watchdog_services_check_failed", YELLOW,
                             f"تعذّر قراءة سجلّ العمليات: {e}", "services")]
    now_dt = datetime.datetime.now()
    window_s = float(duration_s or 90) + 15
    started_at = (now_dt - datetime.timedelta(seconds=window_s)).isoformat(
        timespec="seconds")
    finished_at = now_dt.isoformat(timespec="seconds")
    seen: dict[str, dict] = {}
    for r in rows:
        if r.get("kind") != "service_failure":
            continue
        at = r.get("at") or ""
        if not (started_at <= at <= finished_at):
            continue
        ctx = r.get("context") or {}
        svc = str(ctx.get("service") or "")
        if not svc or svc in seen:
            continue
        human = _SERVICE_FINDING_AR.get(svc, f"خدمة «{svc}» تعطّلت أثناء التشغيلة.")
        seen[svc] = {"service": svc, "severity": YELLOW,
                    "detail_ar": human, "reason": r.get("reason")}
    services = list(seen.values())
    findings = [_finding(f"service_failure_{svc}", YELLOW, s["detail_ar"],
                         "services") for svc, s in seen.items()]
    return services, findings


def _cost_bands(kind: str) -> tuple[float, float]:
    """(سقف التكلفة، سقف المدّة بالثواني) — config-driven لا رقمٌ صلب في
    المنطق؛ افتراضيات معقولة (`/research` قرب هدف <10 دقائق/D-06 §E3،
    `/analyze` مسارٌ مجانيٌّ خفيف)."""
    if kind == "research":
        cost = float(os.environ.get("SILK_WATCHDOG_RESEARCH_COST_BAND_USD", "5.0"))
        dur = float(os.environ.get("SILK_WATCHDOG_RESEARCH_DURATION_BAND_S", "600"))
    else:
        cost = float(os.environ.get("SILK_WATCHDOG_ANALYZE_COST_BAND_USD", "0.5"))
        dur = float(os.environ.get("SILK_WATCHDOG_ANALYZE_DURATION_BAND_S", "90"))
    return cost, dur


def _check_economics(kind: str, economics: dict, dr: dict
                     ) -> tuple[dict, list[dict]]:
    cost = economics.get("cost_usd_estimate")
    duration = economics.get("stage_total_seconds")
    cost_band, dur_band = _cost_bands(kind)
    findings = []
    cost_status = "n/a" if cost is None else ("high" if cost > cost_band else "ok")
    dur_status = "n/a" if duration is None else ("slow" if duration > dur_band else "ok")
    if cost_status == "high":
        findings.append(_finding(
            "cost_band_exceeded", YELLOW,
            f"تكلفة التشغيلة (${cost}) تجاوزت النطاق المتوقَّع (${cost_band}).",
            "economics"))
    if dur_status == "slow":
        findings.append(_finding(
            "duration_band_exceeded", YELLOW,
            f"مدّة التشغيلة ({duration}ث) تجاوزت النطاق المتوقَّع ({dur_band}ث).",
            "economics"))
    unpriced = economics.get("cost_unpriced_models") or []
    if unpriced:
        findings.append(_finding(
            "unpriced_model", YELLOW,
            f"نموذج/نماذج بلا سعر مسجّل: {unpriced} — التكلفة المعروضة تُقلِّل "
            "الفاتورة الحقيقية.", "economics"))
    return {
        "cost_usd": cost, "cost_band_usd": cost_band, "cost_status": cost_status,
        "duration_s": duration, "duration_band_s": dur_band, "duration_status": dur_status,
        "llm_calls": economics.get("llm_calls"), "tool_calls": economics.get("tool_calls"),
        "tariff_path": _tariff_path(dr),
    }, findings


def _check_failures(dr: dict) -> tuple[dict, list[dict]]:
    if not dr:
        return {"missions_failed": [], "max_tokens_truncated": False}, []
    failed = [k for k, m in (dr.get("missions") or {}).items() if m.get("failed")]
    truncated = bool(((dr.get("report") or {}).get("unresolved_notes")))
    findings = []
    if failed:
        findings.append(_finding(
            "missions_failed", YELLOW,
            f"بعثة/بعثات فشلت بلا نتائج: {failed}.", "failures"))
    return {"missions_failed": failed, "max_tokens_truncated": truncated}, findings


def observe(result: dict, kind: str, analysis_id: int | None = None) -> dict | None:
    """السطر الوحيد الذي يستدعيه `api.py` — احسب سجلَّ صحّةٍ لتشغيلةٍ
    منتهية وخزّنه. **لا يرفع استثناءً أبداً** (PART 4 — الحماية الذاتية):
    أيّ عطلٍ داخلي يُعاد كسجلٍّ يحمل `self_error` بدل أن يُسقِط التحليل أو
    يصل المستخدم. `result`: نتيجة `/analyze` أو `/research` الخام (قبل أو
    بعد `_json`، كلاهما آمن — قراءة فقط)."""
    try:
        return _observe_unsafe(result, kind, analysis_id)
    except Exception as e:  # noqa: BLE001 — الحارس يراقب نفسه أيضاً (PART 4-2)
        log.warning("watchdog observe() crashed for kind=%s: %s", kind, e)
        try:
            import silk_ops_log
            silk_ops_log.record_error(
                "watchdog_self_failure", f"الحارس تعطّل: {type(e).__name__}: {e}",
                context={"kind": kind, "analysis_id": analysis_id})
        except Exception:  # noqa: BLE001
            pass
        record = {
            "analysis_id": analysis_id, "kind": kind, "product": None,
            "market": None, "overall": YELLOW,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "contracts": {}, "economics": {}, "services": [],
            "failures": {}, "findings": [_finding(
                "watchdog_self_failure", YELLOW,
                f"الحارس تعطّل في التشغيلة {analysis_id} ({kind}): "
                f"{type(e).__name__}.", "self")],
            "self_error": f"{type(e).__name__}: {e}",
        }
        _store(record)
        return record


def _observe_unsafe(result: dict, kind: str, analysis_id: int | None) -> dict:
    view = result.get("view") or {}
    dr = (view.get("deep_research") or {}) if kind == "research" else {}
    economics = result.get("data_economics") or {}
    market = ((result.get("market") or {}).get("iso3")
             or (result.get("market") or {}).get("name_en"))
    now = datetime.datetime.now().isoformat(timespec="seconds")

    findings: list[dict] = []
    contracts: dict = {}

    contracts["hs_gate"], f1 = _check_hs_gate(result)
    contracts["badge_body"], f2 = _check_badge_body(dr)
    contracts["cross_market_leak"], f3 = _check_cross_market_leak(
        analysis_id, (result.get("market") or {}).get("iso3"))
    contracts["leaks"], f4 = _check_leaks(dr)
    contracts["stale_tags"], f5 = _check_stale_tags(dr)
    contracts["price_sanity"], f6 = _check_price_sanity(dr)
    contracts["no_fabrication"], f7 = _check_no_fabrication(dr)
    qg = (dr.get("quality_gate") or {}) if dr else {}
    qg_verdict = qg.get("verdict")
    contracts["quality_gate"] = {
        "status": qg_verdict or "n/a",
        "detail": f"{len(qg.get('findings') or [])} ملاحظة" if qg_verdict else ""}
    f8 = []
    if qg_verdict == "FAIL":
        f8.append(_finding("quality_gate_fail", RED,
                           "بوابة الجودة (Wave 10) أعادت FAIL على التقرير.",
                           "quality_gate"))
    elif qg_verdict == "PASS-WITH-WARNINGS":
        f8.append(_finding("quality_gate_warn", YELLOW,
                           "بوابة الجودة أعادت PASS-WITH-WARNINGS.",
                           "quality_gate"))

    econ_out, f9 = _check_economics(kind, economics, dr)
    failures_out, f10 = _check_failures(dr)
    services, f11 = _check_services(economics.get("stage_total_seconds"))

    for fl in (f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11):
        findings.extend(fl)

    overall = GREEN
    for fnd in findings:
        if _SEVERITY_RANK[fnd["severity"]] > _SEVERITY_RANK[overall]:
            overall = fnd["severity"]

    record = {
        "analysis_id": analysis_id, "kind": kind,
        "product": result.get("product"), "market": market,
        "overall": overall, "created_at": now,
        "contracts": contracts, "economics": econ_out, "services": services,
        "failures": failures_out, "findings": findings, "self_error": None,
    }
    _store(record)
    return record


# ── PART 3 — عقل الاتجاه: تجميعٌ عند الطلب، لا يعتمد على cron ────────────────

def trend_report(records: list[dict] | None = None, n: int = 50) -> dict:
    """اتجاهاتٌ عبر آخر `n` تشغيلة — يكشف التآكل البطيء (تكلفة تزحف، لجوءٌ
    متكرّرٌ للمصادر الاحتياطية) الذي لا يظهر في فحصٍ لتشغيلةٍ واحدة."""
    records = records if records is not None else list_records(n)
    if not records:
        return {"count": 0}
    by_kind: dict = {}
    for r in records:
        by_kind.setdefault(r.get("kind") or "?", []).append(r)

    def _series(rs, path):
        out = []
        for r in rs:
            v = r
            for p in path:
                v = (v or {}).get(p) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                out.append(v)
        return out

    out: dict = {"count": len(records), "by_kind": {}}
    for kind, rs in by_kind.items():
        costs = _series(rs, ("economics", "cost_usd"))
        durations = _series(rs, ("economics", "duration_s"))
        violations = sum(1 for r in rs if r.get("overall") == RED)
        yellows = sum(1 for r in rs if r.get("overall") == YELLOW)
        tariff_paths = [r.get("economics", {}).get("tariff_path")
                        for r in rs if r.get("economics", {}).get("tariff_path")]
        wto_n = tariff_paths.count("wto")
        wits_n = tariff_paths.count("wits")
        service_fallbacks = sum(len(r.get("services") or []) for r in rs)
        out["by_kind"][kind] = {
            "runs": len(rs),
            "cost_trend": {"first": costs[-1] if costs else None,
                          "last": costs[0] if costs else None,
                          "avg": round(sum(costs) / len(costs), 2) if costs else None},
            "duration_trend": {"first": durations[-1] if durations else None,
                               "last": durations[0] if durations else None,
                               "avg": round(sum(durations) / len(durations), 1)
                               if durations else None},
            "contract_violation_rate": round(violations / len(rs), 2),
            "advisory_rate": round(yellows / len(rs), 2),
            "wto_vs_wits_rate": {"wto": wto_n, "wits": wits_n},
            "service_fallback_count": service_fallbacks,
        }
    return out


# ── PART 2 — التقرير المستقل القابل للتنزيل ─────────────────────────────────

_OVERALL_AR = {GREEN: "أخضر — آخر التشغيلات نظيفة",
              YELLOW: "أصفر — ملاحظات تحتاج مراجعة",
              RED: "أحمر — خرق عقد مرصود"}


def overall_badge(records: list[dict] | None = None, n: int = 20) -> dict:
    records = records if records is not None else list_records(n)
    if not records:
        return {"overall": GREEN, "label_ar": _OVERALL_AR[GREEN], "runs_checked": 0}
    worst = GREEN
    for r in records:
        if _SEVERITY_RANK.get(r.get("overall"), 0) > _SEVERITY_RANK[worst]:
            worst = r["overall"]
    return {"overall": worst, "label_ar": _OVERALL_AR[worst],
           "runs_checked": len(records)}


def render_report_md(records: list[dict] | None = None, n: int = 50) -> str:
    """تقرير مراقبة المنصّة — md مستقلّ تماماً عن أي مُصدِّر تحليل (PART 2-2:
    التصدير ملفٌّ منفصلٌ بذاته، لا مشتقّ من `silk_reports.py`)."""
    records = records if records is not None else list_records(n)
    today = datetime.date.today().isoformat()
    badge = overall_badge(records)
    trend = trend_report(records)
    lines = [f"# تقرير مراقبة المنصّة — {today}", "",
             f"**الحالة العامة:** {badge['label_ar']} "
             f"({badge['runs_checked']} تشغيلة مفحوصة)", "",
             f"> {KNOWN_OPEN_BACKLOG_NOTE}", "",
             "## التشغيلات الأخيرة", "",
             "| التشغيلة | التاريخ | المنتج/السوق | الحالة | ما رُصد | الشدة |",
             "|---|---|---|---|---|---|"]
    for r in records[:30]:
        aid = r.get("analysis_id") or "—"
        pm = f"{r.get('product') or '—'} / {r.get('market') or '—'}"
        overall = _OVERALL_AR.get(r.get("overall"), r.get("overall"))
        top = sorted(r.get("findings") or [],
                    key=lambda f: -_SEVERITY_RANK.get(f.get("severity"), 0))
        what = top[0]["message_ar"] if top else "لا ملاحظات"
        sev = top[0]["severity"] if top else "—"
        lines.append(f"| {aid} | {r.get('created_at', '—')} | {pm} | "
                     f"{overall} | {what} | {sev} |")
    lines += ["", "## اتجاهات (آخر التشغيلات)", ""]
    for kind, t in trend.get("by_kind", {}).items():
        lines.append(f"### {kind}")
        lines.append(f"- عدد التشغيلات: {t['runs']}")
        lines.append(f"- التكلفة: أحدث={t['cost_trend']['last']} "
                     f"| متوسط={t['cost_trend']['avg']} "
                     f"| أقدم={t['cost_trend']['first']}")
        lines.append(f"- المدّة (ث): أحدث={t['duration_trend']['last']} "
                     f"| متوسط={t['duration_trend']['avg']} "
                     f"| أقدم={t['duration_trend']['first']}")
        lines.append(f"- معدّل خرق العقود: {t['contract_violation_rate']*100:.0f}%")
        lines.append(f"- معدّل الملاحظات الصفراء: {t['advisory_rate']*100:.0f}%")
        lines.append(f"- التعريفة: WTO={t['wto_vs_wits_rate']['wto']} "
                     f"مقابل WITS={t['wto_vs_wits_rate']['wits']}")
        lines.append(f"- لجوءٌ لمصادر احتياطية/أعطال خدمات: "
                     f"{t['service_fallback_count']}")
        lines.append("")
    return "\n".join(lines)
