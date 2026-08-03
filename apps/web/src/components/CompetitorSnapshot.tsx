"use client";

import { useTranslations } from "next-intl";
import type { CompetitorSnapshot as Snapshot } from "@/lib/types";

export function CompetitorSnapshot({ snapshot }: { snapshot: Snapshot }) {
  const t = useTranslations("markets");
  const exporters = snapshot.top_exporters ?? [];
  const maxShare = Math.max(1, ...exporters.map((e) => e.share_pct));

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
      <h3 className="font-semibold text-gray-900">{t("competitors")}</h3>
      <div className="mt-2 flex gap-6 text-sm">
        <div>
          <p className="text-gray-500">{t("totalImports")}</p>
          <p className="tabular font-bold text-gray-900">
            ${abbreviate(snapshot.total_import_usd ?? 0)}
          </p>
        </div>
        {snapshot.trend_pct != null && (
          <div>
            <p className="text-gray-500">{t("trend")}</p>
            <p
              className={`tabular font-bold ${
                snapshot.trend_pct >= 0 ? "text-brand-600" : "text-red-600"
              }`}
            >
              {snapshot.trend_pct >= 0 ? "+" : ""}
              {snapshot.trend_pct}%
            </p>
          </div>
        )}
      </div>

      <p className="mt-4 text-xs font-medium text-gray-500">{t("topExporters")}</p>
      <ul className="mt-2 space-y-1.5">
        {exporters.slice(0, 6).map((e) => (
          <li key={e.exporter_iso2} className="flex items-center gap-2">
            <span className="w-28 shrink-0 truncate text-sm text-gray-700">{e.exporter_name}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full rounded-full bg-brand-400"
                style={{ width: `${(e.share_pct / maxShare) * 100}%` }}
              />
            </div>
            <span className="tabular w-12 text-end text-xs text-gray-500">{e.share_pct}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function abbreviate(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(Math.round(n));
}
