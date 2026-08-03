"""وكيل المنافسين المُسمّين لسِلك — Silk named-competitors agent (wave 3, #1).

يسدّ فجوة خيط ١ في محرّك التقاطع القادم: `CompetitionAgent` القائم يرتّب
**دولاً** مورّدة (Comtrade)، وهذا الوكيل يرشّح **شركات/علامات** منافسة بالاسم
في السوق المستهدف عبر بحث الويب (Serper — طبقة مجانية بمفتاح).

الصدق قبل كل شيء: بحث الويب لا "يعرف" المنافسين — يعيد **مرشحين غير
مُتحقَّق منهم** (عنوان/مقتطف/رابط) بثقة منخفضة (0.4) وملاحظة صريحة بذلك.
ترقية الملفات المهيكلة (explee) تأتي عبر `/deepen` لاحقاً. بلا مفتاح أو شبكة:
`DataPoint(None)` موسوم — لا اختلاق (المبدأ التأسيسي).

يرث `BaseAgent` (الموجة ٢): `PAID=False`، والفشل الصامت مستحيل بنيوياً.
"""
from __future__ import annotations

import logging

from silk_data_layer import DataPoint, _today
from silk_agents import BaseAgent, AgentReport
from silk_websearch_agent import web_search

log = logging.getLogger(__name__)

_CANDIDATE_NOTE = ("مرشَّح من بحث الويب — غير مُتحقَّق؛ أكّده قبل الاعتماد. "
                   "Web-search candidate, unverified.")


class NamedCompetitorsAgent(BaseAgent):
    """وكيل المنافسين المُسمّين — company-level competitor candidates by name."""

    PAID = False
    PREF_KEY = "competition"
    SOURCE = "Web Search (Serper)"

    def __init__(self) -> None:
        super().__init__("NamedCompetitorsAgent")

    def _execute(self, task: dict) -> AgentReport:
        """رشّح منافسين بالاسم — competitor-brand candidates for product×market.

        task keys: product (name, ar/en), market (country name/ISO, for the
        query), num (default 5). Keyless/offline -> failed + tagged None.
        """
        product = (task.get("product") or "").strip()
        market = (task.get("market") or "").strip()
        if not product or not market:
            return AgentReport(self.name, [], True,
                               "لا منتج أو سوق — missing product or market")
        # استعلام إنجليزي بنيّة منافسة صريحة — English intent query is sharper.
        query = f"top {product} brands manufacturers competitors in {market}"
        raw = web_search(query, num=int(task.get("num", 5)))
        real = [f for f in raw if f.value is not None]
        if not real:
            note = raw[0].note if raw else "no results"
            return AgentReport(self.name, raw, True,
                               f"لا مرشحي منافسة — no competitor candidates ({note})")
        findings = [
            DataPoint(f.value, self.SOURCE, 0.4,
                      f"{_CANDIDATE_NOTE} | query='{query}'", _today())
            for f in real
        ]
        return AgentReport(self.name, findings, False,
                           f"{len(findings)} competitor candidate(s) for "
                           f"'{product}' in {market} (unverified)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Silk NamedCompetitorsAgent — keyless/offline => tagged None, "
          "no fabricated companies")
    rep = NamedCompetitorsAgent().run({"product": "dates", "market": "Germany"})
    print(f"  [{'FAILED' if rep.failed else 'ok'}] {rep.summary}")
