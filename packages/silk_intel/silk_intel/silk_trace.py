"""تتبّع تشغيلات البحث العميق — Silk research trace logging (الموجة ٦، V5).

كل بعثة تكتب أحداث جولاتها (البرومبت المُرسَل، كل نداء أداة بمدخله/مخرجه،
الردّ الخام، البنود المُسقَطة وسببها، الزمن) إلى `data/traces/{trace_id}.jsonl`
عند تفعيل التتبّع صراحة — contextvar (نفس نمط `silk_context`)، صفر أثر
خارج `trace_context()`. كل نص يمرّ عبر `silk_diagnostics._redact` قبل
الكتابة — نفس انضباط تعقيم الأسرار القائم، لا آلية جديدة.

أداة التنقيح الأساسية (§docs/TUNING.md): شغّل بعثة واحدة بـ
`silk_missions.deep_research(dry_run=True, only_agent="pricing_scout")`،
افحص أثرها، عدّل `silk_missions.MISSIONS[key]["instructions"]`، أعد.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime
import json
import logging
import os

log = logging.getLogger(__name__)

_active: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "silk_trace_active", default=None)


def _default_dir() -> str:
    """مجلد التتبّع الافتراضي — `SILK_TRACE_DIR` أولاً (الاختبارات تعزله
    بتحويله لمجلد مؤقت، نفس نمط SILK_STORE_DB)، ثم data/traces محلياً."""
    return os.environ.get("SILK_TRACE_DIR", "").strip() or "data/traces"


def active() -> bool:
    """هل التتبّع مفعَّل الآن؟ — True فقط داخل trace_context()."""
    return _active.get() is not None


def current_trace_id() -> str | None:
    st = _active.get()
    return st["id"] if st else None


@contextlib.contextmanager
def trace_context(trace_id: str, dir_path: str | None = None):
    """فعّل التتبّع لكتلة — كل record_event() داخلها يُكتب لملف trace_id.jsonl.

    يعمل مع contextvars.copy_context() (نمط silk_missions القائم) فيسري
    داخل خيوط ThreadPoolExecutor الموازية أيضاً — لا حاجة لآلية إضافية.
    `dir_path=None` يحسم المجلد وقت النداء (`_default_dir()`) لا وقت
    التعريف — يحترم SILK_TRACE_DIR حتى لو ضُبط بعد استيراد الوحدة.
    """
    dir_path = dir_path or _default_dir()
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, f"{trace_id}.jsonl")
    token = _active.set({"id": trace_id, "path": path})
    try:
        yield path
    finally:
        _active.reset(token)


def _redacted(obj: object) -> object:
    """طبّق تعقيم الأسرار بعمق على كل قيمة نصية — recursive over str leaves."""
    from silk_diagnostics import _redact
    if isinstance(obj, str):
        return _redact(obj)
    if isinstance(obj, dict):
        return {k: _redacted(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redacted(v) for v in obj]
    return obj


def _write_event(path: str, fields: dict) -> None:
    event = _redacted({
        "ts": datetime.datetime.now(datetime.timezone.utc)
             .isoformat(timespec="milliseconds"),
        **fields})
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # noqa: BLE001 — التتبّع تحسين لا شرط
        log.warning("trace write failed (%s): %s", path, e)


def record_event(**fields) -> None:
    """سجّل حدثاً — no-op بهدوء خارج trace_context (تكلفة صفر افتراضياً).

    فشل الكتابة (قرص ممتلئ/صلاحيات) يُسجَّل تحذيراً ولا يُسقط التشغيلة —
    التتبّع تحسين تشخيصي لا شرط تنفيذ.
    """
    st = _active.get()
    if st is None:
        return
    _write_event(st["path"], fields)


def append_event(trace_id: str, dir_path: str | None = None, **fields) -> None:
    """ألحِق حدثاً بملف تتبّع قائم **خارج** trace_context() — الموجة ١٠:
    بوابة الجودة تعمل بعد إغلاق سياق تتبّع `deep_research()` (النتيجة
    الكاملة/العرض غير جاهزين إلا بعد عودته)، فلا يمكنها استعمال
    `record_event()` (no-op خارج السياق). صمت عند فشل الكتابة — نفس انضباط
    `record_event`، تحسين تشخيصي لا شرط."""
    path = os.path.join(dir_path or _default_dir(), f"{trace_id}.jsonl")
    _write_event(path, fields)


def read_trace(trace_id: str, dir_path: str | None = None) -> list[dict]:
    """اقرأ أحداث تتبّع — قائمة فارغة إن غاب الملف أو فسد سطر (لا استثناء)."""
    path = os.path.join(dir_path or _default_dir(), f"{trace_id}.jsonl")
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001 — ملف غائب = قائمة فارغة
        pass
    return out
