"""قاطع دائرة لكل مصدر — Silk per-source circuit breaker (WS4, resilience).

الغرض: تحليلٌ واحدٌ يُطلق ~١٥٠ نداءً متوازياً لنفس المضيف؛ حين يسقط مصدرٌ
(429/5xx متتالٍ) تُعيد كل نداءةٍ المحاولةَ ٣ مرّاتٍ بتراجُعٍ أسّيّ فيتراكم
الانتظار إلى دقائق — «يعلّق» التشغيلة بدل أن يسقط بسرعةٍ للتِير التالي في
السلسلة. هذا القاطع يفتح بعد N فشلٍ **متتالٍ** لمصدرٍ فيجعل نداءاته اللاحقة
تفشل بسرعة (بلا حلقة إعادةٍ ولا نوم) طوال فترة تهدئةٍ قصيرة، ثم يتحوّل «نصف
مفتوح» فيسمح بمحاولةٍ واحدةٍ استكشافية — نجاحها يغلق الدائرة، فشلها يعيد فتحها.

**لا اختلاق ولا كسر عقد:** القاطع لا يلفّق استجابةً ولا قيمة — يقلّص عدد
المحاولات فقط. الطبقة الأعلى تبقى تُعلن الفجوة كالمعتاد عند الفشل النهائي.
حالة العملية عامة (module-global) كنمط `silk_faostat_agent._auth_blocked`
القائم؛ `reset()` للاختبارات.

A tiny, dependency-free consecutive-failure breaker. Keyed by an arbitrary
string (host / source_id). Opens after `threshold` consecutive failures and
stays open for `cooldown_s`; then half-opens to allow one probe. It never
raises and never fabricates — callers ask `is_open(key)` to decide whether to
fail fast, and report `record_success` / `record_failure`.
"""
from __future__ import annotations

import os
import threading
import time


class CircuitBreaker:
    """قاطع دائرةٍ بعدّاد فشلٍ متتالٍ لكل مفتاح — thread-safe, in-process."""

    def __init__(self, threshold: int = 5, cooldown_s: float = 60.0) -> None:
        self.threshold = max(1, int(threshold))
        self.cooldown_s = max(1.0, float(cooldown_s))
        self._lock = threading.Lock()
        # key -> [consecutive_failures, opened_at_monotonic | 0.0]
        self._state: dict[str, list] = {}

    def is_open(self, key: str) -> bool:
        """هل الدائرة مفتوحة (يجب الفشل السريع) الآن لهذا المفتاح؟

        مفتوحة = بلغ الفشلُ المتتالي العتبةَ **وما زلنا** داخل نافذة التهدئة.
        بعد انقضاء التهدئة تُعَدّ «نصف مفتوحة» ⇒ تُرجِع False (اسمح بمحاولةٍ
        واحدةٍ استكشافية) دون تصفير العدّاد — نجاح المحاولة يصفّره، فشلها
        يجدّد `opened_at` فتُقفَل نافذةٌ جديدة.
        """
        with self._lock:
            st = self._state.get(key)
            if not st or st[0] < self.threshold:
                return False
            opened_at = st[1]
            return (time.monotonic() - opened_at) < self.cooldown_s

    def record_failure(self, key: str) -> None:
        """سجّل فشلاً — زِد العدّاد، وإن بلغ العتبة اطبع طابع الفتح الزمني."""
        with self._lock:
            st = self._state.setdefault(key, [0, 0.0])
            st[0] += 1
            if st[0] >= self.threshold:
                st[1] = time.monotonic()

    def record_success(self, key: str) -> None:
        """سجّل نجاحاً — صفّر العدّاد وأغلِق الدائرة لهذا المفتاح."""
        with self._lock:
            self._state[key] = [0, 0.0]

    def failures(self, key: str) -> int:
        """عدد الفشل المتتالي الحالي لهذا المفتاح — للتشخيص/الاختبار."""
        with self._lock:
            st = self._state.get(key)
            return int(st[0]) if st else 0

    def reset(self, key: str | None = None) -> None:
        """صفّر مفتاحاً واحداً أو الكل — للاختبارات (حالة العملية عامة)."""
        with self._lock:
            if key is None:
                self._state.clear()
            else:
                self._state.pop(key, None)


# القاطع المشترك لنداءات طبقة البيانات (Comtrade/World Bank/…) — عتبة/تهدئة
# قابلتان للضبط بيئياً. عتبة مرتفعة نسبياً كي لا تفتح على وميضٍ عابرٍ واحد.
http_breaker = CircuitBreaker(
    threshold=int(os.environ.get("SILK_CIRCUIT_THRESHOLD", "5")),
    cooldown_s=float(os.environ.get("SILK_CIRCUIT_COOLDOWN_S", "60")),
)
