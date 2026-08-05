"use client";

import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";
import type { AdminOverview } from "@/lib/types";

export default function AdminOverviewPage() {
  const t = useTranslations("admin");
  const { data, loading } = useApi<AdminOverview>("/admin/overview");

  if (loading) return <p className="text-gray-400">…</p>;
  if (!data) return null;

  const tiles: { label: string; value: string }[] = [
    { label: t("statFactories"), value: String(data.factories) },
    { label: t("statActiveCampaigns"), value: String(data.active_campaigns) },
    { label: t("statPending"), value: String(data.pending_approvals) },
    { label: t("statSent"), value: String(data.total_sent) },
    { label: t("statBounceRate"), value: pct(data.bounce_rate) },
    { label: t("statComplaintRate"), value: pct(data.complaint_rate) },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3">
        {tiles.map((tile) => (
          <div
            key={tile.label}
            className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5"
          >
            <p className="text-sm text-gray-500">{tile.label}</p>
            <p className="tabular mt-1 text-2xl font-bold text-gray-900">{tile.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 1000) / 10}%`;
}
