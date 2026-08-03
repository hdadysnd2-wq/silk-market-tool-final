"""وكيل ديناميكيات السوق لسِلك — Silk market-dynamics agent (P2-8، مجاني).

مواصفة المالك: وكيل نوعي واحد يملأ الأقسام السردية (النظرة العامة/
الديناميكيات/الاتجاهات) — يجمع إشارات من طبقة بحث الويب **القائمة** ثم
يصنّفها كلود في أطر معلنة (دوافع/كوابح/فرص/تحديات + بورتر + PESTEL)
**بمصدر لكل نقطة** — نفس انضباط consumer_culture: لا رأي بلا سند.

التدهور الصادق: بلا SEARCH_API_KEY => فجوة معلنة بلا نداء؛ بلا مفتاح
كلود => العناوين الخام تعاد كإشارات غير مصنّفة معلنة؛ نقطة بلا رقم
عنوان سند تُسقط في طبقة التصنيف نفسها. لا اختلاق أبداً.
"""
from __future__ import annotations

import logging
import os

from silk_agents import AgentReport, BaseAgent
from silk_data_layer import DataPoint, _today

log = logging.getLogger(__name__)


class DynamicsAgent(BaseAgent):
    """وكيل الديناميكيات — إشارات ويب مصنّفة في أطر بورتر/PESTEL بمصادرها."""

    PAID = False
    PREF_KEY = "dynamics"
    SOURCE = "Web Search + Claude تصنيف"

    def __init__(self) -> None:
        super().__init__("DynamicsAgent")

    def _execute(self, task: dict) -> AgentReport:
        product = str(task.get("product") or "").strip()
        market = str(task.get("market") or task.get("market_name") or "").strip()
        from silk_websearch_agent import search_key
        if not search_key():
            dp = DataPoint(None, self.SOURCE, 0.0,
                           "يتطلب مفتاح بحث الويب (SEARCH_API_KEY) — "
                           "لم يُحاوَل أي نداء", _today())
            return AgentReport(self.name, [dp], True,
                               "no web-search key — dynamics skipped")

        from silk_websearch_agent import web_search
        queries = [f"{product} market drivers challenges {market}",
                   f"{product} سوق {market} نمو تحديات"]
        headlines: list = []
        for q in queries:
            headlines.extend(web_search(q, num=5))
        real = [h for h in headlines if h.value is not None]
        if not real:
            dp = DataPoint(None, self.SOURCE, 0.0,
                           "بحث الويب لم يعد عناوين لهذا المنتج/السوق",
                           _today())
            return AgentReport(self.name, [dp], True,
                               "no headlines returned")

        from silk_ai_judge import classify_dynamics
        classified = classify_dynamics(product, market, real,
                                       instruction=str(
                                           task.get("instruction") or ""))
        if classified is None:
            # بلا كلود: العناوين الخام إشارات غير مصنّفة — معلنة كذلك.
            dp = DataPoint(
                {"raw_signals": [h.value for h in real[:10]],
                 "classified": False},
                "Web Search (Serper)", 0.4,
                "إشارات خام غير مصنّفة — التصنيف في الأطر يتطلب مفتاح "
                "كلود (ANTHROPIC_API_KEY)", _today())
            return AgentReport(self.name, [dp], False,
                               f"{len(real)} raw signal(s), unclassified")
        dp = DataPoint({**classified, "classified": True}, self.SOURCE, 0.7,
                       f"أطر مصنّفة من {len(real)} عنوان ويب — كل نقطة "
                       "بمصدرها", _today())
        return AgentReport(self.name, [dp], False,
                           "classified dynamics frameworks with citations")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = DynamicsAgent().run({"product": "تمور", "market": "China"})
    print(rep.summary)
    for f in rep.findings:
        print(" -", f.value if f.value else f.note)
