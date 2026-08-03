"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type { Analysis, Product } from "@/lib/types";

/**
 * Stage-1 world funnel for a product: screens every market locally and shows the
 * top-5 export candidates. The transit-port guard (I9) surfaces as a visible
 * badge, and the data year travels under every figure (decision #8). Running the
 * funnel requires a human-confirmed HS code (I2) — the API returns 409 otherwise.
 */
export function WorldFunnel({ product }: { product: Product }) {
  const t = useTranslations("funnel");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirmed = Boolean(product.hs_code && product.hs_confirmed_by_user);

  async function screen() {
    setLoading(true);
    setError(null);
    try {
      setAnalysis(await api.post<Analysis>(`/products/${product.id}/analysis`));
    } catch (err) {
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

      {analysis && (
        <div className="mt-4">
          <p className="text-sm text-gray-500">
            {t("screened", { count: analysis.rankings.length })}
          </p>
          <ul className="mt-3 divide-y divide-gray-100">
            {top5.map((r) => (
              <li key={r.importer_iso3} className="flex items-center justify-between gap-3 py-2">
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
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
