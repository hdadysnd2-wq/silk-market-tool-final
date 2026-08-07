"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { pollUntil } from "@/lib/poll";
import type { Analysis, AnalysisAccepted, FunnelBrief, Product } from "@/lib/types";

/**
 * How long the UI waits for a world-funnel run before giving up. The offline mock
 * finishes in well under a second, but a live Comtrade screen makes real, throttled
 * calls under the per-analysis budget and can take minutes — so this is generous.
 * The worker always finishes regardless; this only bounds how long the UI polls.
 */
const LIVE_SCREEN_TIMEOUT_MS = 180_000;

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
 *
 * `onDiscover` (optional) makes the whole shortlist actionable in one step:
 * "Discover buyers across the top markets" hands back every resolved alpha-2 in
 * the top-5 so the caller can kick off buyer discovery across them.
 */
export function WorldFunnel({
  product,
  onSelectMarket,
  selectedMarket,
  onDiscover,
  discovering,
}: {
  product: Product;
  onSelectMarket?: (iso2: string) => void;
  selectedMarket?: string | null;
  onDiscover?: (markets: string[]) => void;
  discovering?: boolean;
}) {
  const t = useTranslations("funnel");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [brief, setBrief] = useState<FunnelBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const confirmed = Boolean(product.hs_code && product.hs_confirmed_by_user);

  // Per-stage progress label from the analysis status — the funnel is a staged
  // pipeline (pending → ranked → enriched → deepened), not one opaque spinner.
  const stageLabel = (s: string | null): string | null => {
    if (s === "pending" || s === "classified") return t("stagePending");
    if (s === "ranked") return t("stageRanked");
    if (s === "enriched") return t("stageEnriched");
    return null;
  };

  // A terminal `failed` ends the wait IMMEDIATELY with the persisted reason.
  // (The old predicate waited only for success states, so a sub-second failure
  // spun for the full 3-minute poll window and surfaced as a raw timeout.)
  const settleFailed = (run: Analysis) => {
    if (run.status !== "failed") return false;
    setAnalysis(null);
    setError(run.failure_reason || t("analysisFailed"));
    return true;
  };

  async function screen() {
    setLoading(true);
    setError(null);
    setBrief(null);
    try {
      // 202 Accepted: Stage-1 screening runs on a worker. Poll the analysis
      // until it's `ranked` (rankings populated) before reading the result.
      const accepted = await api.post<AnalysisAccepted>(`/products/${product.id}/analysis`);
      const analysisId = accepted.analysis.id;
      const run = await pollUntil(
        () => api.get<Analysis>(`/analyses/${analysisId}`),
        (a) => a.status === "ranked" || a.status === "enriched" || a.status === "failed",
        // A live Comtrade world screen makes real, throttled calls under the
        // per-analysis budget and routinely runs past the 60s default; give it
        // room (the worker keeps going regardless, but the UI should wait).
        { timeoutMs: LIVE_SCREEN_TIMEOUT_MS, onProgress: (a) => setStage(a.status) },
      );
      if (settleFailed(run)) return;
      setAnalysis(run);
      // Brief-first: the decision + sourced numbers + limits headline the result.
      setBrief(await api.get<FunnelBrief>(`/analyses/${analysisId}/brief`));
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

  // Stage 2: budgeted enrichment (applied tariff + PPP) re-ranks the shortlist to
  // the top 5. It's a paid/budgeted step, so it's an explicit action.
  async function refine() {
    if (!analysis) return;
    setEnriching(true);
    setError(null);
    try {
      // 202 Accepted: Stage-2 enrichment runs on a worker and auto-chains the
      // free Stage-3 deep-dive, so the terminal status becomes `deepened`. Poll
      // until either terminal (or a finalist reaches stage 3) before reading.
      const accepted = await api.post<AnalysisAccepted>(`/analyses/${analysis.id}/enrich`);
      const analysisId = accepted.analysis.id;
      const run = await pollUntil(
        () => api.get<Analysis>(`/analyses/${analysisId}`),
        (a) =>
          a.status === "enriched" ||
          a.status === "deepened" ||
          a.status === "failed" ||
          a.rankings.some((r) => r.stage === 3),
        // Stage-2 enrichment chains the Stage-3 deep-dive and hits live tariff/PPP
        // + Comtrade under the budget — same reason as the Stage-1 screen above.
        { timeoutMs: LIVE_SCREEN_TIMEOUT_MS, onProgress: (a) => setStage(a.status) },
      );
      if (settleFailed(run)) return;
      setAnalysis(run);
      setBrief(await api.get<FunnelBrief>(`/analyses/${analysisId}/brief`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEnriching(false);
    }
  }

  const usd = (v: number | null) =>
    v === null ? t("noData") : `$${Math.round(v).toLocaleString("en-US")}`;
  const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);

  const top5 = analysis?.rankings.slice(0, 5) ?? [];
  const enriched = top5.some((r) => r.stage === 2);

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
      {(loading || enriching) && stageLabel(stage) && (
        <p className="mt-2 text-sm text-gray-500">{stageLabel(stage)}</p>
      )}
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
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-gray-500">
              {/* Full funnel transparency (decision: "screened → shortlisted →
                  top 5"): the real world count screened AND the shortlist size;
                  older runs without the world count fall back gracefully. */}
              {t("screened", {
                count: analysis.total_screened ?? analysis.rankings.length,
                shortlisted: analysis.rankings.length,
              })}
            </p>
            {/* Stage 2 — budgeted enrichment re-ranks the shortlist to the top 5. */}
            <button
              type="button"
              onClick={refine}
              disabled={enriching}
              className="shrink-0 rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-60"
            >
              {enriching ? t("refining") : enriched ? t("refined") : t("refine")}
            </button>
          </div>
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
                    {/* Stage-2 signal, when enrichment has run. */}
                    {r.enrichment?.applied_tariff_pct != null && (
                      <div className="text-xs text-gray-400">
                        {t("tariffLabel")} {pct(r.enrichment.applied_tariff_pct)}
                      </div>
                    )}
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

          {(() => {
            // Every top-5 market we hold an alpha-2 for — the shortlist buyer
            // discovery can run across. Unmapped markets are skipped, not faked.
            const markets = top5
              .map((r) => r.market_iso2)
              .filter((iso2): iso2 is string => Boolean(iso2));
            if (!onDiscover || markets.length === 0) return null;
            return (
              <button
                type="button"
                onClick={() => onDiscover(markets)}
                disabled={discovering}
                className="mt-4 w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
              >
                {discovering ? t("discoveringBuyers") : t("discoverTopMarkets")}
              </button>
            );
          })()}
        </div>
      )}
    </section>
  );
}
