"""وكيل قنوات التوزيع لسِلك — Silk distribution-channels agent (wave 3, #2).

يغذّي خيط "أبواب الدخول" في محرّك التقاطع القادم: أي قنوات (سلاسل تجزئة،
جملة، أسواق إلكترونية) تبيع فئة المنتج في السوق المستهدف — عبر بحث الويب
(Serper). سؤالان بقناتين (فعلي/رقمي) في وكيل واحد — كما قررت الرؤية (٩.٢)
للوكلاء الجدد بدل وكيلين منفصلين.

نفس ميثاق الصدق: النتائج **مرشحات غير مُتحقَّق منها** بثقة 0.4 وملاحظة
صريحة؛ بلا مفتاح/شبكة: `DataPoint(None)` موسوم. يرث `BaseAgent` (PAID=False).
"""
from __future__ import annotations

import logging

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport
from silk_websearch_agent import web_search

log = logging.getLogger(__name__)

_CANDIDATE_NOTE = ("مرشَّح من بحث الويب — غير مُتحقَّق؛ أكّده قبل الاعتماد. "
                   "Web-search candidate, unverified.")

# قناتا السؤال — the two channel lenses folded into ONE agent (vision §9.2).
_QUERIES = (
    ("physical", "supermarket chains wholesale distributors selling {p} in {m}"),
    ("digital", "online marketplaces e-commerce sites selling {p} in {m}"),
)


class DistributionChannelsAgent(BaseAgent):
    """وكيل القنوات — retail/wholesale + e-commerce channel candidates."""

    PAID = False
    PREF_KEY = "channels"
    SOURCE = "Web Search (Serper)"

    def __init__(self) -> None:
        super().__init__("DistributionChannelsAgent")

    def _execute(self, task: dict) -> AgentReport:
        """رشّح قنوات البيع — channel candidates (physical + digital lenses).

        task keys: product, market, num (per lens, default 3).
        Keyless/offline -> failed report + tagged None (no fabrication).
        """
        product = (task.get("product") or "").strip()
        market = (task.get("market") or "").strip()
        if not product or not market:
            return AgentReport(self.name, [], True,
                               "لا منتج أو سوق — missing product or market")
        num = int(task.get("num", 3))
        findings: list[DataPoint] = []
        failures: list[DataPoint] = []
        for lens, template in _QUERIES:
            query = template.format(p=product, m=market)
            raw = web_search(query, num=num)
            real = [f for f in raw if f.value is not None]
            if not real:
                failures.extend(raw)
                continue
            findings.extend(
                DataPoint(dict(f.value, channel_type=lens), self.SOURCE, 0.4,
                          f"{_CANDIDATE_NOTE} | lens={lens} | query='{query}'",
                          _today())
                for f in real
            )
        if not findings:
            note = failures[0].note if failures else "no results"
            return AgentReport(self.name, failures, True,
                               f"لا مرشحي قنوات — no channel candidates ({note})")
        return AgentReport(self.name, findings, False,
                           f"{len(findings)} channel candidate(s) for "
                           f"'{product}' in {market} (unverified)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk DistributionChannelsAgent — keyless/offline => tagged None")
    rep = DistributionChannelsAgent().run({"product": "dates", "market": "UAE"})
    print(f"  [{'FAILED' if rep.failed else 'ok'}] {rep.summary}")
