"""سجل الأخطاء التشغيلية لسِلك — Silk operational-error log (SQLite, stdlib only).

ITEM 5ب (مذكّرة العمليات، تدقيق 2026-07-15): آخر N خطأ تشغيلي — فشل تصدير
(docx 501)، فشل كاتب (تقرير None)، رفض حجز (429 بحالة السقف) — يُقرأ عبر
`GET /ops/last-errors` **بلا حاجة لسجلات Railway** (كانت حلقة "الصق لي
البيانات" مستحيلة الإغلاق بلا هذا — البروكسي يمنع الوصول لسجلات النشر).

حلقة محدودة (ring، سقفها `SILK_OPS_LOG_CAP` افتراضياً 200 صفّاً) في قاعدة
مستقلة تماماً (نفس فلسفة `usage.db`) — لا تلمس `silk.db` أبداً. **كل سبب
يصل هذا الملف مُطهَّراً مسبقاً** (`silk_render._strip_internal_plumbing`) من
المستدعي — هذا الملف تخزين محض، لا حارس تعقيم مستقل، فلا يصلح مصدراً مباشراً
لنص كلود خام (المستدعي يتحمّل التطهير قبل النداء، تماماً كنمط silk_storage).

فشل الكتابة/القراءة قناة جانبية صامتة — لا يكسر المسار المستدعي (نفس مبدأ
silk_usage/silk_storage checkpoints)؛ هذا سجل تشخيصي لا حارس مالي، فالقراءة
تتدهور إلى `[]` بأمان بدل الرفض الصارم (fail-closed يخصّ حراس المال فقط).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3

log = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join("data", "ops_errors.db")
_DEFAULT_CAP = 200


def _db_path() -> str:
    """مسار قاعدة السجل — نفس نمط `SILK_USAGE_DB`/`SILK_DATA_DIR` الحالي."""
    explicit = os.environ.get("SILK_OPS_LOG_DB", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("SILK_DATA_DIR", "").strip()
    if base:
        return os.path.join(base, "ops_errors.db")
    return _DEFAULT_PATH


def _connect(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ops_errors ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
        "reason TEXT NOT NULL, context_json TEXT, created_at TEXT NOT NULL)")
    return conn


def record_error(kind: str, reason: str, context: dict | None = None,
                 path: str | None = None) -> None:
    """سجّل خطأً تشغيلياً — `kind`: 'export_failure'|'writer_failure'|
    'reservation_refused'. **`reason` يجب أن يصل مُطهَّراً بالفعل من
    المستدعي** (`silk_render._strip_internal_plumbing`) — هذه الدالة تخزين
    محض ولا تُطهِّر بنفسها. `context`: تفاصيل تشخيصية مهيكلة (analysis_id/
    trace_id/سقف مطلوب...) — أرقام/معرّفات لا نثر كلود حرّ.

    يُبقي آخر `SILK_OPS_LOG_CAP` صفّاً فقط (حلقة، لا نمو بلا حدّ) — يُحذَف
    الأقدم عند كل إدراج يتجاوز السقف. فشل الكتابة يُسجَّل تحذيراً فقط —
    قناة جانبية صامتة، لا تكسر المسار المستدعي أبداً."""
    path = path or _db_path()
    try:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO ops_errors (kind, reason, context_json, "
                "created_at) VALUES (?, ?, ?, ?)",
                (kind, str(reason or ""),
                 json.dumps(context, ensure_ascii=False, default=str)
                 if context else None, now))
            cap = int(os.environ.get("SILK_OPS_LOG_CAP", "") or _DEFAULT_CAP)
            conn.execute(
                "DELETE FROM ops_errors WHERE id NOT IN "
                "(SELECT id FROM ops_errors ORDER BY id DESC LIMIT ?)",
                (max(1, cap),))
    except Exception as e:  # noqa: BLE001 — سجل تشخيصي، لا شرط تشغيل
        log.warning("ops error log write failed (kind=%s): %s", kind, e)


def record_service_failure(service: str, reason: str,
                           context: dict | None = None,
                           path: str | None = None) -> None:
    """سجّل فشلَ خدمةٍ خارجية للمشغّل (Wave 1.5، عائلة C) — one operator-visible
    line per external-service failure, so a silent no-op never hides again.

    `service`: اسم الخدمة العمومي (scraper/comtrade/worldbank/vision/…). يُلفّ
    `record_error` بنوعٍ موحّد `service_failure` وسياقٍ يحمل اسم الخدمة، فيمكن
    فرز كل أعطال الخدمات الخارجية من جدول `ops_errors` بنوعٍ واحد. قناة جانبية
    صامتة (لا تكسر مسار الاستدعاء)."""
    ctx = dict(context or {})
    ctx.setdefault("service", service)
    record_error("service_failure", f"[{service}] {reason}", context=ctx,
                 path=path)


def last_errors(n: int = 20, path: str | None = None) -> list[dict]:
    """آخر `n` خطأ (الأحدث أولاً) — `[]` بلا قاعدة/بلا صفوف، لا استثناء أبداً
    (سجل تشخيصي، ليس حارساً مالياً — القراءة تتدهور بأمان لا ترفض)."""
    path = path or _db_path()
    if not os.path.exists(path):
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT kind, reason, context_json, created_at FROM "
                "ops_errors ORDER BY id DESC LIMIT ?",
                (max(1, int(n)),)).fetchall()
        out = []
        for r in rows:
            ctx = None
            if r["context_json"]:
                try:
                    ctx = json.loads(r["context_json"])
                except Exception:  # noqa: BLE001 — سياق فاسد يُهمَل لا يكسر القراءة
                    ctx = None
            out.append({"kind": r["kind"], "reason": r["reason"],
                       "context": ctx, "at": r["created_at"]})
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("ops error log read failed: %s", e)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    record_error("export_failure", "مثال تجريبي — لا يمثّل خطأً حقيقياً")
    print(last_errors(5))
