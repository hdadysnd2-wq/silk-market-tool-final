"""المخزن الموحّد لسِلك — Silk unified store (M1, خطة إعادة البناء §3).

قاعدة واحدة تنهي انقسام التخزين: مستخدمون/أدوار + مرجع + **مخزن حقائق**
(مؤشرات، تدفقات تجارية، سجل جمع) + تحليلات/قرارات/تقارير/نتائج فعلية.

- SQLite افتراضياً (stdlib)؛ جاهز لـ Postgres عبر DATABASE_URL + psycopg2 إن وُجد
  (محوّل رفيع يترجم مواضع `?` إلى `%s` — نفس SQL المحمول في migrations/).
- ترحيلات متسلسلة من migrations/NNN_*.sql تُتتبَّع في schema_migrations.
- silk_storage.py القديم يبقى يعمل كما هو أثناء الانتقال (facade يُزال في M5)؛
  الاستيراد منه عبر tools/import_legacy.py.
- مبدأ المنصة محفوظ: القيم تُخزَّن مع مصدرها وثقتها وتاريخ سحبها — لا اختلاق.
"""
from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import re
import sqlite3

log = logging.getLogger(__name__)

_DEFAULT_PATH = "data/silk_store.db"
_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "migrations")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _db_path() -> str:
    """مسار المخزن الموحّد — `SILK_STORE_DB` أولاً، ثم اشتقاق من `SILK_DATA_DIR`
    (القرص الدائم في النشر)، ثم الافتراضي المحلي. Explicit var wins;
    SILK_DATA_DIR derives the volume path; local default otherwise."""
    explicit = os.environ.get("SILK_STORE_DB", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("SILK_DATA_DIR", "").strip()
    if base:
        return os.path.join(base, "silk_store.db")
    return _DEFAULT_PATH


def _is_postgres() -> bool:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _q(sql: str) -> str:
    """ترجمة مواضع المعاملات للمحرك الفعّال — translate `?` placeholders to `%s`
    for Postgres. SQLite passthrough. (Same portable SQL everywhere.)"""
    return sql.replace("?", "%s") if _is_postgres() else sql


def connect():
    """اتصال بالمخزن — SQLite by default; Postgres when DATABASE_URL is set and
    psycopg2 is installed (a clear error otherwise — never a silent fallback)."""
    if _is_postgres():
        try:
            import psycopg2  # lazy: optional production driver
        except ImportError as e:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "DATABASE_URL is set to Postgres but psycopg2 is not installed "
                "(pip install psycopg2-binary)") from e
        return psycopg2.connect(os.environ["DATABASE_URL"])
    path = _db_path()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate() -> list[str]:
    """طبّق الترحيلات المتسلسلة — apply migrations/NNN_*.sql in order, once each.

    Returns the list of newly applied versions. Idempotent: re-running applies
    nothing. The tracking table is created by 001 itself (bootstrap-safe)."""
    applied: list[str] = []
    files = sorted(glob.glob(os.path.join(_MIGRATIONS_DIR, "[0-9]*.sql")))
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                           version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)""")
        cur.execute("SELECT version FROM schema_migrations")
        done = {r[0] for r in cur.fetchall()}
        for f in files:
            version = re.match(r"(\d+)", os.path.basename(f)).group(1)
            if version in done:
                continue
            cur.executescript(open(f, encoding="utf-8").read()) if not _is_postgres() \
                else cur.execute(open(f, encoding="utf-8").read())
            cur.execute(_q("INSERT INTO schema_migrations (version, applied_at) "
                           "VALUES (?, ?)"), (version, _now()))
            applied.append(version)
        conn.commit()
    return applied


# ── سياسة الحداثة · freshness policy ────────────────────────────────────────
# نافذة حداثة لكل نوع بيانات: التجارة سنوية وتتغير نادراً (90 يوماً)، مؤشرات
# البنك الدولي (30)، الأسعار متقلبة (7). قابلة للضبط بالبيئة SILK_FRESH_*_DAYS.
# القيمة العتيقة تُخدم فوراً معلَّمة «stale» ويُطلَق تحديث بالخلفية — لا تُعرض
# أبداً كحديثة (قاعدة الإسناد)، ولا تُحجب (القيمة المرصودة خير من فجوة).

_FRESH_DAYS_DEFAULT = {"trade": 90, "indicator": 30, "price": 7}


def fresh_days(kind: str = "trade") -> int:
    """نافذة الحداثة بالأيام لنوع بيانات — env override or per-kind default."""
    default = _FRESH_DAYS_DEFAULT.get(kind, 90)
    raw = os.environ.get(f"SILK_FRESH_{kind.upper()}_DAYS", "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        log.warning("SILK_FRESH_%s_DAYS=%r not an integer — using %d",
                    kind.upper(), raw, default)
        return default


def freshness(retrieved_at: str | None, kind: str = "trade") -> str:
    """حالة حداثة قيمة مخزّنة — 'fresh' | 'stale' | 'unknown'.

    'unknown' لتاريخ غائب/غير قابل للتفسير — يُعامل معاملة العتيق (تحديث)
    لكنه يُميَّز في الإسناد؛ لا تخمين لتاريخ لم يُسجَّل. Never guesses a date.
    """
    if not retrieved_at:
        return "unknown"
    raw = str(retrieved_at).strip()
    try:
        if len(raw) == 10:  # تاريخ يوم فقط — date-only stamps (_today())
            dt = datetime.datetime.fromisoformat(raw).replace(
                tzinfo=datetime.timezone.utc)
        else:
            dt = datetime.datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return "unknown"
    age = datetime.datetime.now(datetime.timezone.utc) - dt
    return "fresh" if age.days < fresh_days(kind) else "stale"


# ── مخزن الحقائق · fact store ────────────────────────────────────────────────

def upsert_indicator(iso3: str, indicator: str, year: int, value,
                     source: str, confidence: float, note: str = "") -> None:
    """أدخل/حدّث مؤشراً بحقيقة أحدث — newest retrieval wins for the same key."""
    with connect() as conn:
        conn.execute(_q(
            "INSERT INTO indicators (iso3, indicator, year, value, source, "
            "confidence, note, retrieved_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT (iso3, indicator, year, source) DO UPDATE SET "
            "value=excluded.value, confidence=excluded.confidence, "
            "note=excluded.note, retrieved_at=excluded.retrieved_at"),
            (iso3, indicator, int(year), value, source, confidence, note, _now()))
        conn.commit()


def get_indicator(iso3: str, indicator: str, year: int | None = None):
    """أحدث قيمة لمؤشر — latest row (highest year when year is None) or None."""
    with connect() as conn:
        if year is None:
            row = conn.execute(_q(
                "SELECT * FROM indicators WHERE iso3=? AND indicator=? "
                "ORDER BY year DESC, retrieved_at DESC LIMIT 1"),
                (iso3, indicator)).fetchone()
        else:
            row = conn.execute(_q(
                "SELECT * FROM indicators WHERE iso3=? AND indicator=? AND year=? "
                "ORDER BY retrieved_at DESC LIMIT 1"),
                (iso3, indicator, int(year))).fetchone()
    return dict(row) if row else None


def upsert_trade_flows(rows: list[dict]) -> int:
    """أدخل/حدّث دفعة تدفقات — bulk upsert; newest retrieval wins. Returns count."""
    n = 0
    with connect() as conn:
        for r in rows:
            conn.execute(_q(
                "INSERT INTO trade_flows (hs6, reporter_iso3, partner_iso3, year, "
                "flow, value_usd, qty_kg, source, retrieved_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (hs6, reporter_iso3, partner_iso3, year, flow) "
                "DO UPDATE SET value_usd=excluded.value_usd, qty_kg=excluded.qty_kg, "
                "source=excluded.source, retrieved_at=excluded.retrieved_at"),
                (r["hs6"], r["reporter_iso3"], r["partner_iso3"], int(r["year"]),
                 r["flow"], r.get("value_usd"), r.get("qty_kg"),
                 r.get("source", "UN Comtrade"), _now()))
            n += 1
        conn.commit()
    return n


def market_imports_from_store(hs6: str, reporter_iso3: str, year: int) -> dict:
    """استيراد سوق من المخزن — {total_usd, partners:[{iso3,value_usd,
    retrieved_at}], retrieved_at}; لا اختلاق: غياب الصفوف = total_usd None
    وقائمة فارغة. `retrieved_at` هو تاريخ **الجلب الأصلي** (أحدث صف) — يُحمل
    مع القيمة كي لا تُعرض قراءة من المخزن كأنها جلب حي اليوم (قاعدة الإسناد).
    Carries the ORIGINAL fetch date so store reads are never presented as live.
    """
    with connect() as conn:
        rows = conn.execute(_q(
            "SELECT partner_iso3, value_usd, retrieved_at FROM trade_flows "
            "WHERE hs6=? AND reporter_iso3=? AND year=? AND flow='M' "
            "ORDER BY value_usd DESC"), (hs6, reporter_iso3, int(year))).fetchall()
    partners = [{"iso3": r[0], "value_usd": r[1], "retrieved_at": r[2]}
                for r in rows if r[0] != "WLD" and r[1] is not None]
    world = [r[1] for r in rows if r[0] == "WLD" and r[1] is not None]
    total = world[0] if world else (sum(p["value_usd"] for p in partners)
                                    if partners else None)
    fetched = max((r[2] for r in rows if r[2]), default=None)
    return {"total_usd": total, "partners": partners, "retrieved_at": fetched}


# ── التحليلات والمخرجات · analyses & outputs ─────────────────────────────────

def save_analysis(result: dict, user_id: int | None = None,
                  legacy_id: int | None = None) -> int:
    """احفظ تحليلاً كاملاً + صفوف أسواقه المسطّحة — full blob + flat projections."""
    def _dpv(c):
        return c.get("value") if isinstance(c, dict) else c

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_q(
            "INSERT INTO analyses (user_id, product, hs6, year_from, year_to, "
            "status, created_at, result_json, legacy_id) VALUES (?,?,?,?,?,?,?,?,?)"),
            (user_id, result.get("product", ""), result.get("hs_code"),
             result.get("year"), result.get("year"), "complete", _now(),
             json.dumps(result, ensure_ascii=False, default=str), legacy_id))
        aid = cur.lastrowid
        for i, m in enumerate(result.get("markets") or [], 1):
            comps = m.get("components", {}) or {}
            cur.execute(_q(
                "INSERT INTO analysis_markets (analysis_id, iso3, rank, total_score, "
                "confidence, comp_market_size, comp_demand, comp_saudi, "
                "comp_competition) VALUES (?,?,?,?,?,?,?,?,?)"),
                (aid, m.get("iso3"), i, m.get("total_score"), m.get("confidence"),
                 _dpv(comps.get("market_size")), _dpv(comps.get("demand_capacity")),
                 _dpv(comps.get("saudi_position")), _dpv(comps.get("competition"))))
        conn.commit()
    return aid


def get_analysis(analysis_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(_q("SELECT * FROM analyses WHERE id=?"),
                           (analysis_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json"))
    return d


def list_analyses(limit: int = 50, after_id: int | None = None) -> list[dict]:
    """قائمة مرقّمة بمؤشر — cursor pagination (id DESC), limit clamped ≤100."""
    limit = max(1, min(int(limit), 100))
    with connect() as conn:
        if after_id is None:
            rows = conn.execute(_q(
                "SELECT id, product, hs6, year_from, status, created_at, legacy_id "
                "FROM analyses ORDER BY id DESC LIMIT ?"), (limit,)).fetchall()
        else:
            rows = conn.execute(_q(
                "SELECT id, product, hs6, year_from, status, created_at, legacy_id "
                "FROM analyses WHERE id < ? ORDER BY id DESC LIMIT ?"),
                (after_id, limit)).fetchall()
    return [dict(r) for r in rows]


def save_decision(analysis_id: int, iso3: str, verdict: str, score, confidence,
                  pillars: dict | None = None, conditions=None, risks=None,
                  first_steps=None) -> int:
    p = pillars or {}
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_q(
            "INSERT INTO decisions (analysis_id, iso3, verdict, score, confidence, "
            "pillar_market, pillar_competition, pillar_regulatory, pillar_profit, "
            "conditions_json, risks_json, first_steps_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"),
            (analysis_id, iso3, verdict, score, confidence,
             p.get("market"), p.get("competition"), p.get("regulatory"),
             p.get("profit"),
             json.dumps(conditions or [], ensure_ascii=False),
             json.dumps(risks or [], ensure_ascii=False),
             json.dumps(first_steps or [], ensure_ascii=False), _now()))
        conn.commit()
        return cur.lastrowid


def set_outcome(analysis_id: int, outcome: str, note: str = "",
                recorded_by: int | None = None) -> bool:
    """سجّل النتيجة الفعلية — upsert؛ False إذا لم يوجد التحليل (لا صف يتيم)."""
    with connect() as conn:
        if not conn.execute(_q("SELECT 1 FROM analyses WHERE id=?"),
                            (analysis_id,)).fetchone():
            return False
        conn.execute(_q(
            "INSERT INTO outcomes (analysis_id, outcome, note, recorded_by, "
            "recorded_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT (analysis_id) DO UPDATE SET outcome=excluded.outcome, "
            "note=excluded.note, recorded_by=excluded.recorded_by, "
            "recorded_at=excluded.recorded_at"),
            (analysis_id, outcome, note, recorded_by, _now()))
        conn.commit()
    return True


# ── المستخدمون · users ───────────────────────────────────────────────────────

def create_user(email: str, role: str, name: str = "",
                pw_hash: str | None = None) -> int:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_q(
            "INSERT INTO users (email, name, role, pw_hash, created_at, active) "
            "VALUES (?,?,?,?,?,1)"),
            (email.strip().lower(), name, role, pw_hash, _now()))
        conn.commit()
        return cur.lastrowid


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(_q("SELECT * FROM users WHERE email=?"),
                           (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("silk_store — unified store; applied migrations:", migrate())
    print("db:", _db_path(), "| postgres:", _is_postgres())


# ── الإعدادات الخادمية · server-side settings (Stage 2A) ─────────────────────

_ALLOWED_KEY_SETTINGS = (
    "COMTRADE_API_KEY", "GOOGLE_MAPS_API_KEY", "SEARCH_API_KEY",
    "SERPER_API_KEY",   # P5: الاسم الشائع لمفتاح Serper — مرادف SEARCH_API_KEY
    "LOCALPRICE_API_KEY", "VOLZA_API_KEY", "EXPLEE_API_KEY", "ANTHROPIC_API_KEY",
)


def set_setting(key: str, value: str) -> bool:
    """احفظ إعداداً مسموحاً — persist an allow-listed source key server-side."""
    if key not in _ALLOWED_KEY_SETTINGS:
        return False
    with connect() as conn:
        conn.execute(_q(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at"), (key, value, _now()))
        conn.commit()
    return True


def load_settings_into_env(overwrite: bool = False) -> int:
    """حمّل الإعدادات المحفوظة إلى بيئة العملية — متغير البيئة يفوز افتراضياً
    (النشر الصريح أعلى سلطة من اللوحة). Returns count loaded."""
    n = 0
    try:
        with connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
    except Exception as e:  # noqa: BLE001 — الإعدادات تحسين لا شرط
        log.debug("settings load skipped: %s", e)
        return 0
    for r in rows:
        k, v = r[0], r[1]
        if k in _ALLOWED_KEY_SETTINGS and v and (overwrite or not os.environ.get(k)):
            os.environ[k] = v
            n += 1
    return n


# ── إعدادات الوكلاء · agent settings (لوحة «إعدادات الوكلاء») ────────────────
# {agent_key: {"on": bool, "cmd": str}} — تفعيل/تعطيل + توجيه نصي لكل وكيل.
# تُحفظ JSONاً واحداً في جدول settings بمفتاح مخصص **خارج** قائمة مفاتيح
# المصادر المسموحة — فلا يمكن تهريب مفتاح مصدر عبر هذه اللوحة، والعكس:
# load_settings_into_env لا يلمس هذا الصف (ليس في القائمة المسموحة).

_AGENT_SETTINGS_KEY = "AGENT_SETTINGS_JSON"


def save_agent_settings(settings: dict) -> None:
    """احفظ إعدادات الوكلاء — persist the whole per-agent settings dict."""
    with connect() as conn:
        conn.execute(_q(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at"),
            (_AGENT_SETTINGS_KEY,
             json.dumps(settings or {}, ensure_ascii=False), _now()))
        conn.commit()


def load_agent_settings() -> dict | None:
    """حمّل إعدادات الوكلاء المحفوظة — the saved dict, or None (لا حفظ بعد).

    أي فشل (قاعدة غائبة/JSON تالف) = None بهدوء — الإعدادات تحسين لا شرط.
    """
    try:
        with connect() as conn:
            row = conn.execute(_q("SELECT value FROM settings WHERE key=?"),
                               (_AGENT_SETTINGS_KEY,)).fetchone()
        got = json.loads(row[0]) if row and row[0] else None
        return got if isinstance(got, dict) and got else None
    except Exception as e:  # noqa: BLE001
        log.debug("agent settings load skipped: %s", e)
        return None


def _normalize_product_key(product: str) -> str:
    """مفتاحُ ذاكرةٍ مطبَّعٌ لاسم منتج — يعيد استعمال تطبيع silk_hs_confirm._norm
    (تشكيلٌ/تنميطُ ألفٍ وياء/تصغيرٌ) كي الأشكال القريبة لنفس المنتج تصيب نفس
    الذاكرة — نواةٌ واحدةٌ لا نسخةٌ موازية قابلة للانحراف."""
    import re
    try:
        from silk_hs_confirm import _norm
        s = _norm(product)
    except Exception:  # noqa: BLE001 -- احتياطٌ محليٌّ لا يكسر التخزين
        s = (product or "").strip().lower()
    return re.sub(r"\s+", " ", s).strip()


def cache_hs_classification(product: str, payload: dict) -> None:
    """خزّن ناتج تصنيف HS العام لمنتجٍ — الموجة ٣ (المصنّف العام،
    `silk_hs_classifier.classify_general`): منتجٌ سبق تصنيفه لا يُعيد نداء
    كلود إطلاقاً (نداءٌ واحدٌ فقط لكل اسم منتج جديد). فشل الكتابة قناة
    جانبية صامتة — التخزين تحسينٌ لا شرط تصنيف."""
    key = _normalize_product_key(product)
    if not key:
        return
    try:
        migrate()
        with connect() as conn:
            conn.execute(_q(
                "INSERT INTO hs_classify_cache (product_key, payload_json, "
                "created_at) VALUES (?,?,?) ON CONFLICT (product_key) DO "
                "UPDATE SET payload_json=excluded.payload_json, "
                "created_at=excluded.created_at"),
                (key, json.dumps(payload or {}, ensure_ascii=False), _now()))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("hs classify cache write skipped (product=%r): %s",
                   product, e)


def get_cached_hs_classification(product: str) -> dict | None:
    """اقرأ ناتج تصنيف HS المخزَّن لمنتجٍ — `None` بلا ذاكرةٍ سابقة (إصابة
    ذاكرة سلبية، لا استثناء). أيّ فشل (قاعدة غائبة/JSON تالف) = None بهدوء."""
    key = _normalize_product_key(product)
    if not key:
        return None
    try:
        migrate()
        with connect() as conn:
            row = conn.execute(
                _q("SELECT payload_json FROM hs_classify_cache "
                   "WHERE product_key=?"), (key,)).fetchone()
        got = json.loads(row[0]) if row and row[0] else None
        return got if isinstance(got, dict) and got else None
    except Exception as e:  # noqa: BLE001
        log.debug("hs classify cache read skipped (product=%r): %s",
                 product, e)
        return None


def get_trade_flow(hs6: str, reporter_iso3: str, partner_iso3: str,
                   year: int, flow: str = "M") -> dict | None:
    """صف تدفق واحد بكامل أعمدته — one flow row (incl. qty_kg) or None. لا اختلاق:
    غياب الصف = None، وقيمة/وزن غائبان يبقيان None في الصف نفسه."""
    with connect() as conn:
        row = conn.execute(_q(
            "SELECT * FROM trade_flows WHERE hs6=? AND reporter_iso3=? "
            "AND partner_iso3=? AND year=? AND flow=? "
            "ORDER BY retrieved_at DESC LIMIT 1"),
            (hs6, reporter_iso3, partner_iso3, int(year), flow)).fetchone()
    return dict(row) if row else None


def record_agent_run(agent: str, hs6: str, iso3: str, status: str,
                     coverage: float, started_at: str, finished_at: str,
                     note: str = "", analysis_id: int | None = None) -> int:
    """سجّل تشغيلة وكيل بحث — Stage 3 §4b: صف لكل تشغيلة لشاشة الإدارة (M6)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_q(
            "INSERT INTO agent_runs (analysis_id, agent, hs6, iso3, status, "
            "coverage, started_at, finished_at, note) VALUES (?,?,?,?,?,?,?,?,?)"),
            (analysis_id, agent, hs6, iso3, status, float(coverage),
             started_at, finished_at, note))
        conn.commit()
        return cur.lastrowid


def get_indicator_series(iso3: str, indicator: str, years: int = 6) -> list[dict]:
    """سلسلة سنوات لمؤشر — last N years (asc) for volatility computations."""
    with connect() as conn:
        rows = conn.execute(_q(
            "SELECT year, value, source, retrieved_at FROM indicators "
            "WHERE iso3=? AND indicator=? AND value IS NOT NULL "
            "ORDER BY year DESC LIMIT ?"), (iso3, indicator, int(years))).fetchall()
    return [dict(r) for r in reversed(rows)]
