"""وكيل المستوردين لسِلك — Silk importers agent (wave 3, #3 — free path).

مستوردون/موزعون مرشّحون بالاسم في السوق المستهدف عبر بحث الويب (Serper) —
كان التدقيق قد وصف هذا الدور بأنه "أضعف وكيل حالياً (best-effort ويب)" وهو
هنا يتأسس صراحةً كطبقة مجانية مرشِّحة: أسماء **غير مُتحقَّق منها** بثقة 0.4.

الترقية الحقيقية تبقى في `/deepen`: `VolzaAgent` (بوالص شحن فعلية) وexplee
(ملفات شركات) — هذا الوكيل يذكّر بذلك في ملاحظاته ولا يدّعي أكثر من العينة.
بلا مفتاح/شبكة: `DataPoint(None)` موسوم. يرث `BaseAgent` (PAID=False).
"""
from __future__ import annotations

import logging

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport
from silk_websearch_agent import web_search

log = logging.getLogger(__name__)

_CANDIDATE_NOTE = ("مرشَّح من بحث الويب — غير مُتحقَّق؛ للأسماء الموثّقة "
                   "(بوالص شحن) فعّل التعميق (Volza). Web candidate, "
                   "unverified — /deepen (Volza) gives documented names.")


class ImportersAgent(BaseAgent):
    """وكيل المستوردين — importer/distributor candidates (free web layer)."""

    PAID = False
    PREF_KEY = "channels"
    SOURCE = "Web Search (Serper)"

    def __init__(self) -> None:
        super().__init__("ImportersAgent")

    def _execute(self, task: dict) -> AgentReport:
        """رشّح مستوردين — importer candidates for product×market.

        task keys: product, market, num (default 5).
        Keyless/offline -> failed report + tagged None (no fabrication).
        """
        product = (task.get("product") or "").strip()
        market = (task.get("market") or "").strip()
        if not product or not market:
            return AgentReport(self.name, [], True,
                               "لا منتج أو سوق — missing product or market")
        query = f"{product} importers distributors wholesale buyers in {market}"
        raw = web_search(query, num=int(task.get("num", 5)))
        real = [f for f in raw if f.value is not None]
        if not real:
            note = raw[0].note if raw else "no results"
            return AgentReport(self.name, raw, True,
                               f"لا مرشحي مستوردين — no importer candidates ({note})")
        findings = [
            DataPoint(f.value, self.SOURCE, 0.4,
                      f"{_CANDIDATE_NOTE} | query='{query}'", _today())
            for f in real
        ]
        return AgentReport(self.name, findings, False,
                           f"{len(findings)} importer candidate(s) for "
                           f"'{product}' in {market} (unverified)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk ImportersAgent — keyless/offline => tagged None")
    rep = ImportersAgent().run({"product": "dates", "market": "Morocco"})
    print(f"  [{'FAILED' if rep.failed else 'ok'}] {rep.summary}")
