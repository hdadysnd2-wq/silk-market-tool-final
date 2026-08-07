"use client";

import { use, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { ProductReport } from "@/lib/types";

function usd(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value < 0 ? "-" : "";
  const n = Math.abs(value);
  if (n >= 1_000_000_000) return `${sign}$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${sign}$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${sign}$${Math.round(n / 1_000)}K`;
  return `${sign}$${Math.round(n).toLocaleString()}`;
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("report");
  const locale = useLocale();
  const isAr = locale === "ar";
  const { data: report, loading } = useApi<ProductReport>(`/products/${id}/report?locale=${locale}`);
  const [downloading, setDownloading] = useState<string | null>(null);

  async function download(path: string, filename: string, kind: string) {
    setDownloading(kind);
    try {
      const blob = await api.blob(path);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(null);
    }
  }

  // The executive multi-market report is the DEFAULT deliverable (Wave 3);
  // the deep report stays available as the on-demand drill-down.
  const downloadExecutive = () =>
    download(`/products/${id}/report/executive`, `silk-executive-${id}.docx`, "executive");
  const downloadDeep = () =>
    download(`/products/${id}/report.docx?locale=${locale}`, `silk-report-${id}.docx`, "deep");
  const downloadHtml = () =>
    download(`/products/${id}/report.html?locale=${locale}`, `silk-report-${id}.html`, "html");

  if (loading) return <p className="text-gray-400">…</p>;
  if (!report) return null;

  const productName = isAr ? report.product.name_ar : report.product.name_en;
  const s = report.summary;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
          <p className="text-gray-500">{productName}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={downloadExecutive}
            disabled={downloading !== null}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {downloading === "executive" ? "…" : t("downloadExecutive")}
          </button>
          <button
            onClick={downloadDeep}
            disabled={downloading !== null}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {downloading === "deep" ? "…" : t("downloadDeep")}
          </button>
          <button
            onClick={downloadHtml}
            disabled={downloading !== null}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {downloading === "html" ? "…" : t("download")}
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat n={s.markets_analyzed} label={t("markets")} />
        <Stat n={s.total_buyers} label={t("buyers")} />
        <Stat n={s.total_contacts} label={t("contacts")} />
        <Stat n={usd(s.total_import_usd)} label={t("importValue")} />
      </div>

      {report.funnel && report.funnel.top_markets.length > 0 && (
        <section className="mt-6 rounded-xl bg-white p-5 ring-1 ring-black/5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold text-gray-900">{t("worldFunnel")}</h2>
            <span className="text-sm text-gray-500">
              {t("shortlisted")}: {report.funnel.shortlisted_count}
            </span>
          </div>
          <ul className="mt-3 divide-y divide-gray-100">
            {report.funnel.top_markets.map((m) => (
              <li key={m.importer_iso3} className="flex items-center justify-between gap-3 py-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-gray-400">#{m.rank}</span>
                  <span className="text-sm font-medium text-gray-900">{m.importer_iso3}</span>
                  {m.is_transit_hub && <Pill warn>{t("transitHub")}</Pill>}
                  {m.is_mirror && (
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                      {t("mirror")}
                    </span>
                  )}
                </div>
                <div className="text-end">
                  <div className="text-sm text-gray-900 tabular-nums">{usd(m.import_usd)}</div>
                  <div className="text-xs text-gray-400">
                    {m.year != null ? `${t("dataYear")} ${m.year}` : "—"}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.markets.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <div className="mt-6 space-y-5">
          {report.markets.map((m) => (
            <section key={m.iso2} className="rounded-xl bg-white p-5 ring-1 ring-black/5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold text-gray-900">
                  {isAr ? m.name_ar : m.name_en} <span className="text-gray-400">({m.iso2})</span>
                  {m.is_gcc && <Pill>GCC</Pill>}
                  {m.is_eu && <Pill warn>EU</Pill>}
                </h2>
                <span className="text-sm text-gray-500">
                  {m.buyer_count} {t("buyers")} · {m.contact_count} {t("contacts")}
                </span>
              </div>

              {m.snapshot && (
                <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm">
                  <span className="text-gray-500">{t("importValue")}: </span>
                  <span className="font-semibold tabular-nums">{usd(m.snapshot.total_import_usd)}</span>
                  {m.snapshot.trend_pct != null && (
                    <span
                      className={`ms-2 ${m.snapshot.trend_pct >= 0 ? "text-brand-700" : "text-amber-700"}`}
                    >
                      {m.snapshot.trend_pct >= 0 ? "▲" : "▼"} {m.snapshot.trend_pct}%
                    </span>
                  )}
                  {m.snapshot.top_exporters.length > 0 && (
                    <div className="mt-1 text-gray-500">
                      {t("competitors")}:{" "}
                      {m.snapshot.top_exporters
                        .slice(0, 3)
                        .map((e) => e.exporter_name || e.exporter_iso2)
                        .join(" · ")}
                    </div>
                  )}
                </div>
              )}

              <ul className="mt-3 divide-y divide-gray-100">
                {m.top_buyers.map((b, i) => (
                  <li key={i} className="py-2">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-medium text-gray-900">
                        {b.name}
                        {b.city && <span className="text-gray-400"> · {b.city}</span>}
                        {b.legal_review_required && <Pill warn>{t("legalReview")}</Pill>}
                      </span>
                      <span className="font-semibold text-brand-700 tabular-nums">
                        {b.relevance_score}
                        <span className="font-normal text-gray-400">/100</span>
                      </span>
                    </div>
                    {b.evidence_summary && (
                      <p className="text-sm text-gray-500">{b.evidence_summary}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ n, label }: { n: number | string; label: string }) {
  return (
    <div className="rounded-xl bg-white p-4 ring-1 ring-black/5">
      <div className="text-2xl font-bold text-brand-700 tabular-nums">{n}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function Pill({ children, warn }: { children: React.ReactNode; warn?: boolean }) {
  return (
    <span
      className={`ms-2 rounded-full px-2 py-0.5 text-xs font-semibold ${
        warn ? "bg-amber-50 text-amber-700" : "bg-brand-50 text-brand-700"
      }`}
    >
      {children}
    </span>
  );
}
