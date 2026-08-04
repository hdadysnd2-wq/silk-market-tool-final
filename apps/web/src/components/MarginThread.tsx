"use client";

import { useTranslations } from "next-intl";
import type { MarginThread as Thread } from "@/lib/types";

/**
 * The competitor margin thread for a market: name + observed price + computed
 * margin (the DoD's competitor-with-margins view). Every figure is computed or a
 * declared gap (I1) — a missing offer, a currency mismatch or a missing price
 * shows "—" with the reason, never a fabricated margin. The "limits" list carries
 * the honest caveats (gross headroom, no FX, prices not yet fetched).
 *
 * `onFetchPrices` (optional) triggers the deepen price fetch so a market with no
 * observed prices yet can be populated in one click.
 */
export function MarginThread({
  thread,
  onFetchPrices,
  fetching,
}: {
  thread: Thread;
  onFetchPrices?: () => void;
  fetching?: boolean;
}) {
  const t = useTranslations("margin");

  const money = (v: number | null, ccy: string | null) =>
    v === null ? "—" : `${ccy ? ccy + " " : ""}${v.toLocaleString("en-US")}`;
  const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
  const marginTone = (v: number | null) =>
    v === null ? "text-gray-400" : v >= 0 ? "text-brand-600" : "text-red-600";

  return (
    <div className="mt-4 rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-gray-900">{t("title")}</h3>
        {onFetchPrices && (
          <button
            type="button"
            onClick={onFetchPrices}
            disabled={fetching}
            className="shrink-0 rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-60"
          >
            {fetching ? t("fetching") : t("fetchPrices")}
          </button>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-6 text-sm">
        <div>
          <p className="text-gray-500">{t("factoryOffer")}</p>
          <p className="tabular font-bold text-gray-900">
            {money(thread.factory_offer, thread.factory_currency)}
          </p>
        </div>
        <div>
          <p className="text-gray-500">{t("medianObserved")}</p>
          <p className="tabular font-bold text-gray-900">
            {money(thread.median_observed_price, thread.factory_currency)}
          </p>
        </div>
        <div>
          <p className="text-gray-500">{t("medianMargin")}</p>
          <p className={`tabular font-bold ${marginTone(thread.median_margin_pct)}`}>
            {pct(thread.median_margin_pct)}
          </p>
        </div>
      </div>

      {thread.competitors.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-100">
          {thread.competitors.map((c) => (
            <li key={c.competitor} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <span className="text-sm font-medium text-gray-900">{c.competitor}</span>
                {c.note && <span className="block text-xs text-gray-400">{c.note}</span>}
              </div>
              <div className="text-end">
                <div className="tabular text-sm text-gray-900">
                  {money(c.observed_price, c.currency)}
                </div>
                <div className={`tabular text-xs font-medium ${marginTone(c.margin_pct)}`}>
                  {t("marginLabel")} {pct(c.margin_pct)}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* The source line under the figures — never omitted (decision #7). */}
      <p className="mt-3 text-xs text-gray-400">{thread.source_line}</p>

      {/* "Limits" — the declared gaps (I1), never compressed away. */}
      {thread.limits.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 ps-5 text-xs text-gray-500">
          {thread.limits.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
