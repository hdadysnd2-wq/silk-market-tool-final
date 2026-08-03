"""تخزين التحليلات لسِلك — Silk analysis persistence (SQLite, stdlib only).

Persists engine.analyze() results to a local SQLite file so analyses can be
listed and re-opened later. Pure stdlib (sqlite3 + json), fully offline. The
.db file is gitignored; nothing here ever touches the network or fabricates.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3

log = logging.getLogger(__name__)

_DEFAULT_PATH = "data/silk.db"


def _db_path() -> str:
    """مسار قاعدة التحليلات وقت النداء — resolve at call time (env or default).

    `SILK_DB` يوجّه الملف لقرص دائم في النشر (Railway volume على /data مثلًا)
    دون حجب ملفات data/ المرجعية؛ يليه اشتقاق من `SILK_DATA_DIR` (متغير واحد
    يوجّه كل المخازن للقرص). Env override for persistent-disk deploys;
    SILK_DATA_DIR derives the path when SILK_DB itself is unset.
    """
    explicit = os.environ.get("SILK_DB", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("SILK_DATA_DIR", "").strip()
    if base:
        return os.path.join(base, "silk.db")
    return _DEFAULT_PATH


def _resolve_data_dir() -> str | None:
    """المجلّد الجذر للتخزين الدائم — the root persistent-storage directory.

    `SILK_DATA_DIR` مباشرةً، وإلا مجلّد `SILK_DB` الصريح. None حين لا توجيه.
    Used by the boot guard and /health to verify the target is a REAL disk.
    """
    base = os.environ.get("SILK_DATA_DIR", "").strip()
    if base:
        return base
    db = os.environ.get("SILK_DB", "").strip()
    if db:
        return os.path.dirname(os.path.abspath(db)) or os.sep
    return None


def _nearest_mountpoint(path: str) -> str:
    """أقرب نقطة تركيب صاعدةً — the nearest mount point at or above `path`.

    يصعد الآباء حتى `os.path.ismount` يصدق؛ يرجّع جذر نظام الملفات إن لم يجد.
    Walks parents until a mount point is found; returns the fs root otherwise.
    """
    p = os.path.abspath(path)
    while p != os.path.dirname(p):
        if os.path.ismount(p):
            return p
        p = os.path.dirname(p)
    return p


def persistence_status() -> dict:
    """حالة القرص الدائم الفعلية — actual persistent-storage status.

    يستخدمها حارس الإقلاع و/health للتمييز بين «المتغيّر مكتوب» و«قرص دائم
    حقيقي مركّب وقابل للكتابة». حادثة حيّة (بلاغ المالك): `SILK_DATA_DIR`
    كان مضبوطًا لكن **لا وحدة تخزين مركّبة على مساره** — فكل تحليل مدفوع كان
    يُكتب على جذر حاوية Railway الفاني ويُمحى عند كل إعادة نشر، والحارس القديم
    (فحص أن المتغيّر غير فارغ فقط) لم ينتبه.

    الحقول:
    - `configured`: أيّ متغيّر تخزين موجَّه أصلًا.
    - `path`: المجلّد الجذر المحلول (أو None).
    - `mountpoint`: أقرب نقطة تركيب فوق المسار.
    - `is_mount`: المسار على وحدة تخزين مركّبة فعلًا (لا جذر الحاوية `/` الفاني).
    - `writable`: نجحت كتابة ملف مجسّ فعليّ ثم حذفه.
    """
    d = _resolve_data_dir()
    st: dict = {"configured": bool(d), "path": d, "mountpoint": None,
                "is_mount": False, "writable": False}
    if not d:
        return st
    mp = _nearest_mountpoint(d)
    st["mountpoint"] = mp
    # جذر الحاوية (overlay على `/`) ليس قرصًا دائمًا؛ وحدة Railway تُركَّب على
    # مسارها الخاص فتظهر كنقطة تركيب منفصلة. تساوي المسار الجذر = لا وحدة.
    st["is_mount"] = os.path.abspath(mp) != os.path.abspath(os.sep)
    # مجسّ كتابة فعلي باسم فريد (mkstemp) — /health قد يُنادى بالتوازي، فاسمٌ
    # ثابت يجعل نداءين يتسابقان على نفس الملف (حذفٌ أثناء كتابة) فيُبلَّغ
    # writable=False زورًا. mkstemp يضمن التفرّد ولا تصادم.
    try:
        import tempfile
        os.makedirs(d, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".silk_persist_probe_", dir=d)
        try:
            os.write(fd, b"ok")
        finally:
            os.close(fd)
            os.remove(probe)
        st["writable"] = True
    except OSError:
        st["writable"] = False
    return st


def _connect(path: str) -> sqlite3.Connection:
    """افتح اتصالًا وأنشئ المجلد — open a connection, making parent dir if needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> None:
    """أنشئ الجداول (idempotent) — create tables if absent. Safe to call repeatedly.

    الموجة ١: عمودا `outcome` + `outcome_date` (سجل النتائج الفعلية التراكمي).
    قواعد قديمة بلا العمودين تُرحَّل بـ ALTER TABLE آمن لا يمسّ أي بيانات قائمة.

    حادثة نقطة تفتيش/استئناف (P0): أعمدة `status`/`kind`/`request_json`/
    `updated_at` على `analyses` + جدول `research_missions` جديد — كل بعثة
    من الاثنتي عشرة تُخزَّن فور اكتمالها (لا بعد التشغيلة كاملة)، فتشغيلة
    فاشلة منتصف الطريق لا تُعيد دفع ثمن ما اكتمل بالفعل (راجع
    `docs/DEEP_RESEARCH_DECISIONS.md`، حادثة نفاد الاعتمادات).
    """
    path = path or _db_path()
    with _connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analyses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "product TEXT, hs_code TEXT, year INTEGER, created_at TEXT, "
            "preliminary INTEGER, json_blob TEXT, "
            "outcome TEXT, outcome_date TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS market_scores ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "analysis_id INTEGER, country TEXT, iso3 TEXT, "
            "total_score REAL, confidence REAL, "
            "FOREIGN KEY(analysis_id) REFERENCES analyses(id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_missions ("
            "analysis_id INTEGER, mission_key TEXT, status TEXT, "
            "report_json TEXT, completed_at TEXT, market_iso3 TEXT, "
            "PRIMARY KEY (analysis_id, mission_key))"
        )
        # ترحيل قواعد أقدم بلا العمود (البلاغ الحي — تسرّب اليمن↔الكويت،
        # 2026-07-21): additive migration; existing rows untouched (market_iso3
        # NULL لصفوفٍ قديمة => `load_mission_checkpoints` لا تُطأطئها، فقط
        # الصفوف الجديدة تُختَم بسوقها).
        _rm_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(research_missions)")}
        if "market_iso3" not in _rm_cols:
            conn.execute(
                "ALTER TABLE research_missions ADD COLUMN market_iso3 TEXT")
        # جدول خامل: لم يبقَ مستدعٍ لدوالّه. يُبقى إنشاؤه (CREATE IF NOT
        # EXISTS، إضافي) حفاظاً على أي صفوف قديمة على القرص الدائم (قاعدة
        # عدم حذف بيانات silk.db)؛ لا كتابة/قراءة جديدة عليه بعد اليوم.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS product_snapshots ("
            "hs_code TEXT, market_iso3 TEXT, product TEXT, "
            "snapshot_json TEXT, created_at TEXT, "
            "PRIMARY KEY (hs_code, market_iso3))"
        )
        # ترحيل القواعد الأقدم — additive migration; existing rows untouched.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
        for col in ("outcome", "outcome_date", "status", "kind",
                   "request_json", "updated_at",
                   # التقدّم الحيّ (المرحلة/العدّادات/التكلفة المُقدَّرة حتى
                   # الآن) — لقطة تُحدَّث أثناء تشغيلة /research الجارية،
                   # يقرأها GET /research/{id}/status. مستقلّة عن json_blob
                   # النهائي (لا يُكتَب إلا عند الاكتمال).
                   "progress_json",
                   # حقول شريط «بحوثي السابقة» (بلاغ حي — تحليلات مكتملة
                   # مدفوعة الثمن لا تظهر لاحقاً فيُعاد دفع ثمنها): تُملأ من
                   # نفس نموذج العرض الموحّد (silk_render.build_view) عند
                   # الحفظ — عرض سريع في القائمة بلا تفسير json_blob الكامل
                   # لكل صفّ، نفس فلسفة market_scores أعلاه.
                   "market_name", "verdict_label", "cost_usd"):
            if col not in existing:
                conn.execute(f"ALTER TABLE analyses ADD COLUMN {col} TEXT")


def _sidebar_summary_fields(result: dict) -> tuple[str | None, str | None, float | None]:
    """(اسم السوق، تسمية الحكم، التكلفة التقديرية) لصفّ شريط «بحوثي السابقة»
    — استيراد كسول لـ`silk_render` (يبقي هذه الوحدة بلا اعتماد وقت الاستيراد،
    نفس نمط الاستيراد الكسول القائم في المشروع) عبر نموذج العرض الموحّد
    فلا مسار حساب مواز؛ فشل العرض لا يكسر الحفظ أبداً (قناة جانبية صامتة)."""
    try:
        from silk_render import build_view, _VERDICT_LABELS_AR
        view = build_view(result)
        market_name = (view.get("header") or {}).get("target_market")
        dr = view.get("deep_research")
        if dr:
            verdict_label = dr.get("verdict_label")
        else:
            tone = (view.get("decision") or {}).get("tone")
            verdict_label = _VERDICT_LABELS_AR.get(tone)
        cost = (view.get("data_economics") or {}).get("cost_usd_estimate")
        return market_name, verdict_label, (float(cost) if cost is not None else None)
    except Exception as e:  # noqa: BLE001 — عرض شريط لا شرط حفظ
        log.warning("sidebar summary fields extraction failed: %s", e)
        return None, None, None


def save_analysis(result: dict, path: str | None = None,
                  analysis_id: int | None = None) -> int:
    """خزّن نتيجة تحليل وأعد المعرّف — store an analyze() result, return its row id.

    The full dict is json.dumps'd into json_blob; per-market scores are also
    flattened into market_scores for quick listing/querying, and a sidebar
    summary (market/verdict/cost) is derived from the same canonical view —
    quick listing without re-parsing json_blob per row (see GET /analyses).

    `analysis_id`: مرّره لتحديث صفّ **موجود بالفعل** بدل إدراج صفّ جديد —
    يستعمله مسار `/research` (نقطة تفتيش/استئناف، P0) حين يكون المعرّف
    قد خُصِّص مسبقاً عبر `create_research_run` قبل بدء البعثات، فتنتهي
    التشغيلة بنفس المعرّف الذي بدأت به لا معرّفاً جديداً.
    """
    path = path or _db_path()
    init_db(path)
    blob = json.dumps(result, ensure_ascii=False, default=_json_default)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    market_name, verdict_label, cost_usd = _sidebar_summary_fields(result)
    with _connect(path) as conn:
        if analysis_id is not None:
            conn.execute(
                "UPDATE analyses SET product = ?, hs_code = ?, year = ?, "
                "preliminary = ?, json_blob = ?, status = 'completed', "
                "updated_at = ?, market_name = ?, verdict_label = ?, "
                "cost_usd = ? WHERE id = ?",
                (result.get("product"), result.get("hs_code"),
                 result.get("year"), 1 if result.get("preliminary") else 0,
                 blob, now, market_name, verdict_label,
                 str(cost_usd) if cost_usd is not None else None, analysis_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO analyses "
                "(product, hs_code, year, created_at, preliminary, "
                "json_blob, status, kind, updated_at, market_name, "
                "verdict_label, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, 'completed', 'analyze', ?, ?, ?, ?)",
                (result.get("product"), result.get("hs_code"),
                 result.get("year"), now,
                 1 if result.get("preliminary") else 0, blob, now,
                 market_name, verdict_label,
                 str(cost_usd) if cost_usd is not None else None),
            )
            analysis_id = int(cur.lastrowid)
        for row in result.get("markets", []):
            conn.execute(
                "INSERT INTO market_scores "
                "(analysis_id, country, iso3, total_score, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                (analysis_id, row.get("country"), row.get("iso3"),
                 row.get("total_score"), row.get("confidence")),
            )
    log.info("saved analysis id=%s product=%s", analysis_id, result.get("product"))
    return analysis_id


# ── نقطة تفتيش/استئناف البحث العميق (P0، حادثة نفاد الاعتمادات) ─────────────

def create_research_run(product: str, market_iso3: str, hs_code: str | None,
                        request_snapshot: dict,
                        path: str | None = None,
                        market_name: str | None = None) -> int:
    """خصّص معرّف تشغيلة بحث عميق **قبل** تشغيل أي بعثة — allocate the
    analysis_id up front so per-mission checkpoints can attach to it from
    the very first mission that finishes, not only at the very end.

    `request_snapshot`: كل ما يلزم لاستئناف التشغيلة لاحقاً بلا إعادة
    إرسال الطلب الأصلي (product/market/hs_code/product_card/agent_prefs/...)
    — يُقرأ عبر `get_research_run` حين يُمرَّر `resume=<id>` لاحقاً.

    `market_name`: اسم عرض (عربي/إنجليزي) لصفّ شريط «بحوثي السابقة» أثناء
    التشغيلة الجارية (قبل اكتمال `save_analysis` الذي يستنتجه من العرض
    الموحّد) — يتراجع لـ`market_iso3` إن غاب، لا يترك السطر بلا اسم سوق.
    """
    path = path or _db_path()
    init_db(path)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    placeholder = json.dumps({"status": "running", "product": product,
                              "hs_code": hs_code}, ensure_ascii=False)
    with _connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO analyses "
            "(product, hs_code, year, created_at, preliminary, json_blob, "
            "status, kind, request_json, updated_at, market_name) "
            "VALUES (?, ?, NULL, ?, 1, ?, 'running', 'research', ?, ?, ?)",
            (product, hs_code, now, placeholder,
             json.dumps(request_snapshot, ensure_ascii=False,
                        default=_json_default), now,
             market_name or market_iso3),
        )
        return int(cur.lastrowid)


def update_research_status(analysis_id: int, status: str,
                           path: str | None = None) -> None:
    """حدّث حالة تشغيلة — 'running'|'completed'|'failed'. لا يمسّ json_blob."""
    path = path or _db_path()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _connect(path) as conn:
        conn.execute(
            "UPDATE analyses SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, analysis_id))


def update_research_progress(analysis_id: int, path: str | None = None,
                             **fields) -> None:
    """حدّث لقطة تقدّم حيّة لتشغيلة بحث عميق جارية — تُدمَج (قراءة-تعديل-
    كتابة) مع أي لقطة سابقة بنفس الصفّ، لا تستبدلها بالكامل.

    الحقول المتوقَّعة: `stage` ('missions'|'analyst'|'writer'|'reviewer'|
    'done')، `started_at` (ISO، يُضبَط أول مرة فقط ولا يُستبدَل لاحقاً حتى
    لو أُعيد تمريره — الاستدعاءات اللاحقة تُمرّره بأمان بلا تكرار منطق)،
    `llm_calls`/`tool_calls`/`cost_usd_estimate`/`cost_unpriced_models` —
    قناة جانبية صامتة (فشل الكتابة لا يُسقط التشغيلة، نفس مبدأ نقاط تفتيش
    البعثات). قيمة None في `fields` تُهمَل (لا تمسح حقلاً محفوظاً بلا قصد).
    """
    path = path or _db_path()
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT progress_json FROM analyses WHERE id = ?",
            (analysis_id,)).fetchone()
        current: dict = {}
        if row and row["progress_json"]:
            try:
                current = json.loads(row["progress_json"])
            except Exception:  # noqa: BLE001 — لقطة فاسدة تُستبدَل لا تكسر الكتابة
                current = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k == "started_at" and current.get("started_at"):
                continue  # يُضبَط أول مرة فقط — لا يتحرّك مع كل لقطة لاحقة
            current[k] = v
        conn.execute(
            "UPDATE analyses SET progress_json = ? WHERE id = ?",
            (json.dumps(current, ensure_ascii=False, default=_json_default),
             analysis_id))


def get_research_progress(analysis_id: int, path: str | None = None) -> dict:
    """اللقطة الحيّة الحالية — قاموس فارغ إن لم تُسجَّل بعد/لا قاعدة. لا اختلاق."""
    path = path or _db_path()
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT progress_json FROM analyses WHERE id = ?",
            (analysis_id,)).fetchone()
    if not row or not row["progress_json"]:
        return {}
    try:
        return json.loads(row["progress_json"])
    except Exception:  # noqa: BLE001
        return {}


def _reconcile_leaked_usd(analysis_id: int, created_at: object,
                          progress: dict | None, path: str | None) -> bool:
    """صالِح حجز دولارٍ متسرّب لتشغيلةٍ فاشلة/عالقة — **ذرّي الفكرة idempotent**
    عبر وسم `usd_reconciled` في لقطة التقدّم (تدقيق v2 الموجة ٢، البند #3).

    تشغيلةٌ تفشل رشيقاً (استثناء مُلتقَط => `mark_research_failed`) لم تكن تُصالِح
    حجزها الدولاري (`try_reserve_usd`) أبداً، والمكنَس القديم يمسّ 'running' فقط —
    فيبقى الحجز محجوزاً حتى دوران الدلو اليومي، فيسدّ السقف على تشغيلاتٍ لم تكتمل.
    - **idempotent**: صفّ موسوم `usd_reconciled` => لا إعادة خصم (المسار الفاشل
      والمكنَس قد يلمسان الصفّ نفسه؛ الوسم يمنع الخصم المزدوج).
    - يُصالَح لحجوزات **دلو اليوم** فقط (`created_at` اليوم) — حجزُ يومٍ سابق زال
      بدوران الدلو، فيُوسَم دون خصمٍ من اليوم خطأً.
    يعيد True إن جرى خصمٌ فعليّ، وإلا False."""
    if (progress or {}).get("usd_reconciled"):
        return False
    today = datetime.date.today().isoformat()
    if (str(created_at or ""))[:10] != today:
        update_research_progress(analysis_id, path=path, usd_reconciled=True)
        return False
    import silk_usage  # lazy: keep silk_storage importable offline/keyless
    expected = float(os.environ.get("SILK_RESEARCH_EXPECTED_USD", "3.0"))
    try:
        actual = float((progress or {}).get("cost_usd_estimate") or 0.0)
    except (TypeError, ValueError):
        actual = 0.0
    silk_usage.reconcile_usd(reserved=expected, actual=actual)
    update_research_progress(analysis_id, path=path, usd_reconciled=True)
    return True


def reconcile_failed_run_usd(analysis_id: int, path: str | None = None) -> bool:
    """صالِح حجز تشغيلةٍ فشلت رشيقاً — يُستدعى فور `mark_research_failed` في مسار
    الاستثناء (تدقيق v2 الموجة ٢، البند #3). يقرأ الصفّ (created_at + لقطة التقدّم)
    ويفوّض للمُصالِح الـidempotent. فشل القراءة لا يُسقط شيئاً (قناة جانبية)."""
    path = path or _db_path()
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT created_at, progress_json FROM analyses WHERE id = ?",
                (analysis_id,)).fetchone()
        if row is None:
            return False
        progress = {}
        if row["progress_json"]:
            try:
                progress = json.loads(row["progress_json"])
            except Exception:  # noqa: BLE001
                progress = {}
        return _reconcile_leaked_usd(analysis_id, row["created_at"], progress, path)
    except Exception as e:  # noqa: BLE001 — المصالحة قناة جانبية لا تُسقط شيئاً
        log.warning("reconcile_failed_run_usd(%s) failed: %s", analysis_id, e)
        return False


def mark_research_failed(analysis_id: int, error_message: str,
                         path: str | None = None) -> None:
    """سجّل فشل تشغيلة (استثناء غير متوقع خارج الحلقات المحروسة أصلاً) —
    الحالة 'failed' + سبب موجز في json_blob؛ نقاط تفتيش البعثات المكتملة
    فعلاً **تبقى** في research_missions (لا تُمسَح) — استئناف لاحق يقرأها."""
    path = path or _db_path()
    init_db(path)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    blob = json.dumps({"status": "failed",
                       "error": str(error_message)[:2000]}, ensure_ascii=False)
    with _connect(path) as conn:
        conn.execute(
            "UPDATE analyses SET status = 'failed', json_blob = ?, "
            "updated_at = ? WHERE id = ?", (blob, now, analysis_id))


def reap_orphan_research_runs(stale_minutes: int | None = None,
                              path: str | None = None) -> list[int]:
    """احصد التشغيلات اليتيمة: صفوف 'running' عالقة (تعطّل عملية/إعادة نشر
    منتصف الطريق) تُوسَم 'failed'، ويُصالَح حجز الدولار المتسرّب لكلٍّ إلى
    الفعلي-حتى-الآن. يعيد قائمة المعرّفات المحصودة (فارغة إن لا شيء).

    **لماذا.** تعطّل العملية (إعادة نشر Railway، SIGKILL) لا يُشغِّل
    `mark_research_failed` ولا `reconcile_usd`، فيبقى الصفّ 'running' أبداً
    وحجزُه الدولاري المسبق (`try_reserve_usd`) بلا مصالحة — يتراكم فيسدّ
    السقف اليومي على تشغيلات لم تُكمَل («حجز بلا تسوية يُبقي التقدير محجوزاً»
    — عقد `reconcile_usd`).

    - **العتبة** `SILK_ORPHAN_STALE_MINUTES` (افتراضياً ٣٠ دقيقة — أطول من
      أطول تشغيلة مشروعة ~١٠ دقائق، فلا تُحصَد تشغيلة حيّة). `updated_at`
      يُبقى حديثاً بكل لقطة تقدّم/تفتيش بعثة، فصفّ لم يُلمَس منذ العتبة =
      عمليته ماتت يقيناً.
    - **المصالحة** إلى الفعلي-حتى-الآن (تكلفة آخر لقطة تقدّم؛ غائبة => ٠.٠،
      لا اختلاق). تُطبَّق فقط لتشغيلة حُجِزت في **دلو اليوم** (`created_at`
      اليوم)، إذ يعمل `reconcile_usd` على دلو اليوم؛ حجزُ يوم سابق زال أصلاً
      بدوران الدلو اليومي فلا يُخصَم من اليوم خطأً.
    - نقاط تفتيش البعثات المكتملة **تبقى** (mark_research_failed لا يمسّها)،
      فاستئناف لاحق يقرأها — «الاستئناف بالقروش، إعادة التشغيل بالدولارات».
    """
    stale = (int(os.environ.get("SILK_ORPHAN_STALE_MINUTES", "30"))
             if stale_minutes is None else int(stale_minutes))
    path = path or _db_path()
    if not os.path.exists(path):
        return []
    init_db(path)
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(minutes=stale)).isoformat(timespec="seconds")
    today = now.date().isoformat()
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, progress_json FROM analyses "
            "WHERE status = 'running' AND updated_at IS NOT NULL "
            "AND updated_at < ?", (cutoff,)).fetchall()
        # تدقيق v2 الموجة ٢ (البند #3): المكنَس يمسح أيضاً صفوف 'failed' لم
        # يُصالَح حجزها بعد — تشغيلةٌ فشلت رشيقاً قبل هذا الإصلاح، أو تعطّلت في
        # النافذة الضيّقة بين `mark_research_failed` والمصالحة. دلو اليوم فقط
        # (الحجز خارجه زال بدوران الدلو). الوسم `usd_reconciled` يمنع تكراره.
        failed_rows = conn.execute(
            "SELECT id, created_at, progress_json FROM analyses "
            "WHERE status = 'failed' AND created_at >= ?", (today,)).fetchall()
    reaped: list[int] = []
    for row in rows:
        aid = int(row["id"])
        progress = {}
        if row["progress_json"]:
            try:
                progress = json.loads(row["progress_json"])
            except Exception:  # noqa: BLE001 — لقطة فاسدة => {}، لا تكسر الحصاد
                progress = {}
        mark_research_failed(
            aid, "orphaned: صفّ 'running' عالق حصده المكنَس (تعطّل عملية/"
            "إعادة نشر منتصف الطريق)", path=path)
        _reconcile_leaked_usd(aid, row["created_at"], progress, path)
        reaped.append(aid)
    # صفوف 'failed' غير المُصالَحة (لا تُوسَم 'reaped' — لم تكن عالقةً 'running').
    for row in failed_rows:
        progress = {}
        if row["progress_json"]:
            try:
                progress = json.loads(row["progress_json"])
            except Exception:  # noqa: BLE001
                progress = {}
        _reconcile_leaked_usd(int(row["id"]), row["created_at"], progress, path)
    if reaped:
        log.info("orphan reaper: حصد %d تشغيلة عالقة: %s", len(reaped), reaped)
    return reaped


def get_research_run(analysis_id: int, path: str | None = None) -> dict | None:
    """معلومات تشغيلة بحث عميق (بلا json_blob الكامل) — لاستعمالَي الاستئناف
    ونقطة نهاية الحالة (`GET /research/{id}/status`). None إن لم توجد."""
    path = path or _db_path()
    if not os.path.exists(path):
        return None
    init_db(path)  # ترحيل آمن للقواعد الأقدم قبل قراءة الأعمدة الجديدة
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT id, product, hs_code, created_at, updated_at, status, "
            "kind, request_json FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["request"] = json.loads(d.get("request_json") or "{}")
    except Exception:  # noqa: BLE001 — سجل فاسد = طلب فارغ، لا كسر
        d["request"] = {}
    return d


def save_mission_checkpoint(analysis_id: int, mission_key: str, report: object,
                            path: str | None = None,
                            market_iso3: str | None = None) -> None:
    """خزّن نتيجة بعثة واحدة فور اكتمالها — the checkpoint write itself
    (P0). `report`: AgentReport حيّ — يُسلسَل كما تُسلسَل نتائج التحليل
    الكاملة (`_json_default`، dataclasses.asdict).

    `market_iso3` (البلاغ الحي — تسرّب اليمن↔الكويت، 2026-07-21): يُختَم
    على كل صفّ كي تستطيع `load_mission_checkpoints` رفض أيّ نقطة تفتيش
    محفوظة لسوقٍ آخر — نقطة اختناق شبكة أمان بنيوية، لا تعتمد وحدها على
    ضبط طبقة `/research` العليا."""
    path = path or _db_path()
    init_db(path)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    status = "failed" if getattr(report, "failed", False) else "completed"
    blob = json.dumps(report, ensure_ascii=False, default=_json_default)
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO research_missions "
            "(analysis_id, mission_key, status, report_json, completed_at, "
            "market_iso3) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(analysis_id, mission_key) DO UPDATE SET "
            "status = excluded.status, report_json = excluded.report_json, "
            "completed_at = excluded.completed_at, "
            "market_iso3 = excluded.market_iso3",
            (analysis_id, mission_key, status, blob, now, market_iso3))


def _agent_report_from_dict(d: dict):
    """أعد بناء AgentReport حيّ من JSON مُخزَّن — the resume-side inverse of
    `_json_default`'s dataclasses.asdict. يُستعمَل فقط عند تحميل نقاط
    تفتيش — لا يمسّ أي مسار تشغيل حيّ آخر."""
    from silk_agents import AgentReport
    from silk_data_layer import DataPoint
    findings = []
    for f in (d.get("findings") or []):
        findings.append(DataPoint(**f) if isinstance(f, dict) else f)
    return AgentReport(agent_name=d.get("agent_name", ""), findings=findings,
                       failed=bool(d.get("failed")),
                       summary=d.get("summary", ""))


def load_mission_checkpoints(analysis_id: int,
                             path: str | None = None,
                             market_iso3: str | None = None) -> dict:
    """كل نقاط تفتيش البعثات المكتملة لتشغيلة — {mission_key: AgentReport}.
    قاموس فارغ إن لم توجد قاعدة/تشغيلة — لا استثناء، لا اختلاق.

    `market_iso3` (شبكة أمان تحدّد النطاق — البلاغ الحي: تسرّب اليمن↔الكويت،
    2026-07-21): إن مُرِّر، أيّ صفّ مختوم بسوقٍ **آخر** يُرفَض ويُسجَّل تحذيراً
    بدل أن يُعاد كأنه صحيح — البعثة تُعامَل كغير مكتملة فتُعاد لاحقاً على
    السوق الصحيح لا تُسلَّم بيانات سوقٍ خاطئ. صفوفٌ قديمة بلا ختم
    (`market_iso3 IS NULL`، من قبل هذه الميزة) تمرّ كما كانت — لا انحدار
    على تشغيلات محفوظة سابقاً."""
    path = path or _db_path()
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT mission_key, report_json, market_iso3 "
            "FROM research_missions WHERE analysis_id = ?", (analysis_id,)
        ).fetchall()
    out = {}
    for r in rows:
        stored_iso3 = r["market_iso3"] if "market_iso3" in r.keys() else None
        if market_iso3 and stored_iso3 and stored_iso3 != market_iso3:
            log.warning(
                "checkpoint %s/%s belongs to market %s, not requested %s — "
                "rejected (cross-market leak guard)",
                analysis_id, r["mission_key"], stored_iso3, market_iso3)
            continue
        try:
            out[r["mission_key"]] = _agent_report_from_dict(
                json.loads(r["report_json"]))
        except Exception as e:  # noqa: BLE001 — نقطة تفتيش فاسدة تُهمَل لا تكسر الاستئناف
            log.warning("corrupt checkpoint %s/%s ignored: %s",
                       analysis_id, r["mission_key"], e)
    return out


def checkpoint_market_iso3s(analysis_id: int, path: str | None = None) -> set[str]:
    """أسواق **مختلفة** مختومة على نقاط تفتيش التشغيلة — قراءة خام بلا فلترة
    (على النقيض من `load_mission_checkpoints`)، للحارس (`silk_watchdog`):
    كشف أي بقايا سوقٍ آخر وصلت الجدول رغم بوّابة API (البند ٣٦، تسرّب
    اليمن↔الكويت) — شبكة أمان قابلة للرصد لا الرفض وحده. صفوفٌ قديمة بلا
    ختم (`market_iso3 IS NULL`) تُهمَل — لا انحدار."""
    path = path or _db_path()
    if not os.path.exists(path):
        return set()
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT market_iso3 FROM research_missions "
            "WHERE analysis_id = ? AND market_iso3 IS NOT NULL", (analysis_id,)
        ).fetchall()
    return {r["market_iso3"] for r in rows if r["market_iso3"]}


def mission_status_map(analysis_id: int, path: str | None = None) -> dict:
    """{mission_key: 'completed'|'failed'} للبعثات المخزَّنة فقط — البعثات
    الغائبة تعني 'pending' (لم تكتمل/تبدأ بعد) من منظور المستدعي."""
    path = path or _db_path()
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT mission_key, status FROM research_missions "
            "WHERE analysis_id = ?", (analysis_id,)
        ).fetchall()
    return {r["mission_key"]: r["status"] for r in rows}


def set_outcome(analysis_id: int, outcome: str,
                path: str | None = None) -> bool:
    """سجّل نتيجة تحليل فعلية — record what actually happened (wave 1).

    يضبط `outcome` (نص حر: "entered/GO confirmed/رفض العميل"...) و`outcome_date`
    (تاريخ اليوم). يعيد False إن لم يوجد التحليل — لا إنشاء ضمني.
    path=None يقرأ المسار الافتراضي وقت النداء (قابل للتوجيه في الاختبارات).
    """
    path = path or _db_path()
    if not os.path.exists(path):
        return False
    init_db(path)  # يضمن وجود العمودين على القواعد الأقدم (ترحيل آمن)
    with _connect(path) as conn:
        cur = conn.execute(
            "UPDATE analyses SET outcome = ?, outcome_date = ? WHERE id = ?",
            (outcome, datetime.date.today().isoformat(), analysis_id),
        )
    return cur.rowcount > 0


def list_analyses(path: str | None = None) -> list[dict]:
    """اسرد التحليلات المحفوظة — list saved analyses (newest first), metadata only.

    `status` (running/completed/failed)، `market_name`/`verdict_label`
    (شريط «بحوثي السابقة» — silk_storage._sidebar_summary_fields)، و
    `cost_usd` (نص رقمي مُخزَّن، يُحوَّل عائماً هنا — None إن غاب أو تعذّر
    التحويل، لا اختلاق صفر) — قائمة أقدم من هذه الحقول تعرضها `None` صراحة."""
    path = path or _db_path()
    if not os.path.exists(path):
        return []
    init_db(path)  # ترحيل آمن للقواعد الأقدم قبل قراءة عمودي outcome
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT id, product, hs_code, year, created_at, preliminary, "
            "outcome, outcome_date, status, market_name, verdict_label, "
            "cost_usd FROM analyses ORDER BY id DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["cost_usd"] = float(d["cost_usd"]) if d.get("cost_usd") else None
        except (TypeError, ValueError):
            d["cost_usd"] = None
        out.append(d)
    return out


def get_analysis(analysis_id: int, path: str | None = None) -> dict | None:
    """أعد تحليلًا كاملًا — fetch one full analysis dict, or None if absent.

    path=None يقرأ المسار الافتراضي وقت النداء (قابل للتوجيه في الاختبارات).
    """
    path = path or _db_path()
    if not os.path.exists(path):
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT json_blob FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["json_blob"])


# جدول product_snapshots خاملٌ — لا دوالّ قراءة/كتابة له بعد اليوم. يبقى
# إنشاؤه (CREATE IF NOT EXISTS في init_db) حفاظاً على أي صفوف قديمة على
# القرص الدائم (قاعدة عدم حذف بيانات silk.db).


def _json_default(obj: object) -> object:
    """تسلسل DataPoint وغيره — JSON fallback (DataPoint and dataclasses -> dict)."""
    import dataclasses
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import tempfile
    demo_path = os.path.join(tempfile.mkdtemp(), "silk_demo.db")
    fake = {  # هيكل فقط، ليست بيانات حقيقية — STRUCTURE only, not real data.
        "product": "demo-product", "hs_code": "000000", "year": 2022,
        "preliminary": True,
        "markets": [{"country": "Demo-Land", "iso3": "XXX",
                     "total_score": 0.0, "confidence": 0.0}],
    }
    aid = save_analysis(fake, demo_path)
    print("saved id:", aid)
    print("list:", list_analyses(demo_path))
    print("get product:", get_analysis(aid, demo_path)["product"])
