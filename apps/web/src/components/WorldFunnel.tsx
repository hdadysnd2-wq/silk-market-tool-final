"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type { Analysis, FunnelBrief, Product } from "@/lib/types";

/**
 * Stage-1 world funnel for a product: screens every market locally and shows the
 * brief-first output (decision #7) — the decision, three sourced numbers and the
 * "limits of this report" section — above the top-5 export candidates. The
 * transit-port guard (I9) surfaces as a visible badge, and the data year travels
 * under every figure (decision #8). Running the funnel requires a human-confirmed
 * HS code (I2) — the API returns 409 otherwise.
 *
 * A top-5 row that carries a resolved alpha-2 (`market_iso2`) is a live entry
 * point into that country's competitor deep-dive: clicking it calls
 * `onSelectMarket`. A market we hold no alpha-2 for stays non-clickable — a
 * declared gap, never a dead link.
 */
export function WorldFunnel({
  product,
  onSelectMarket,
  selectedMarket,
}: {
  product: Product;
  onSelectMarket?: (iso2: string) => void;
  selectedMarket?: string | null;
}) {
  const t = useTranslations("funnel");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [brief, setBrief] = useState<FunnelBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirmed = Boolean(product.hs_code && product.hs_confirmed_by_user);

  async function screen() {
    setLoading(true);
    setError(null);
    setBrief(null);
    try {
      const run = await api.post<Analysis>(`/products/${product.id}/analysis`);
      setAnalysis(run);
      // Brief-first: the decision + sourced numbers + limits headline the result.
      setBrief(await api.get<FunnelBrief>(`/analyses/${run.id}/brief`));
    } catch (err) {
      setAnalysis(null);
      setError(
        err instanceof ApiError && err.status === 409
          ? t("confirmFirst")
          : (err as Error).message,
      );
    } finally {
      setLoading(false);
    }
  }

  const usd = (v: number | null) =>
    v === null ? t("noData") : `$${Math.round(v).toLocaleString("en-US")}`;
  const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);

  const top5 = analysis?.rankings.slice(0, 5) ?? [];

  return (
    <section className="mt-8 rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-gray-900">{t("title")}</h2>
        <button
          onClick={screen}
          disabled={!confirmed || loading}
          className="shrink-0 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {loading ? t("screening") : t("screenButton")}
        </button>
      </div>

      {!confirmed && <p className="mt-2 text-sm text-gray-500">{t("confirmFirst")}</p>}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {brief && (
        <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-4">
          {/* The decision — the headline of the brief (decision #7). */}
          <p className="text-base font-semibold text-gray-900">{brief.decision}</p>

          {brief.decisive_numbers.length > 0 && (
            <div className="mt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                {t("decisiveNumbers")}
              </h3>
              <ul className="mt-1 space-y-1.5">
                {brief.decisive_numbers.map((fig) => (
                  <li key={fig.label} className="text-sm">
                    <span className="font-medium text-gray-900">{fig.label}</span>
                    {" · "}
                    <span className="text-gray-900">{fig.value ?? t("noData")}</span>
                    {/* The source line under every number — never omitted (decision #7). */}
                    <span className="block text-xs text-gray-400">{fig.source}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.competitive_position.length > 0 && (
            <div className="mt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                {t("competitivePosition")}
              </h3>
              <ul className="mt-1 list-disc space-y-1 ps-5 text-sm text-gray-600">
                {brief.competitive_position.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          {/* "Limits of this report" — the declared gaps, never compressed away. */}
          {brief.limits.length > 0 && (
            <div className="mt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                {t("limits")}
              </h3>
              <ul className="mt-1 list-disc space-y-1 ps-5 text-sm text-gray-600">
                {brief.limits.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {analysis && (
        <div className="mt-4">
          <p className="text-sm text-gray-500">
            {t("screened", { count: analysis.rankings.length })}
          </p>
          <ul className="mt-3 divide-y divide-gray-100">
            {top5.map((r) => {
              const iso2 = r.market_iso2;
              const clickable = Boolean(iso2 && onSelectMarket);
              const isSelected = Boolean(iso2 && selectedMarket && iso2 === selectedMarket);
              const rowInner = (
                <>
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-gray-400">#{r.rank}</span>
                    <span className="text-sm font-medium text-gray-900">{r.importer_iso3}</span>
                    {r.is_transit_hub && (
                      <span
                        className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700"
                        title={t("transitHubHint")}
                      >
                        {t("transitHub")}
                      </span>
                    )}
                    {r.is_mirror && (
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                        {t("mirror")}
                      </span>
                    )}
                  </div>
                  <div className="text-end">
                    <div className="text-sm text-gray-900">{usd(r.import_usd)}</div>
                    <div className="text-xs text-gray-400">
                      {r.year ? t("yearLabel", { year: r.year }) : t("noData")} · {t("cagr")}{" "}
                      {pct(r.cagr_3y)}
                    </div>
                  </div>
                </>
              );
              return (
                <li key={r.importer_iso3}>
                  {clickable ? (
                    <button
                      type="button"
                      onClick={() => onSelectMarket!(iso2!)}
                      aria-pressed={isSelected}
                      title={t("viewCompetitors")}
                      className={`flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-start transition-colors hover:bg-gray-50 ${
                        isSelected ? "bg-brand-50" : ""
                      }`}
                    >
                      {rowInner}
                    </button>
                  ) : (
                    <div className="flex items-center justify-between gap-3 px-2 py-2">{rowInner}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
