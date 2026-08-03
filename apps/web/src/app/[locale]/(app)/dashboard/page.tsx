"use client";

import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";
import type { DashboardStats } from "@/lib/types";

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const { data, loading } = useApi<DashboardStats>("/dashboard");

  if (loading) return <p className="text-gray-400">…</p>;
  if (!data) return null;

  const hasActivity = data.campaigns > 0;

  const tiles: { label: string; value: string }[] = [
    { label: t("campaigns"), value: String(data.campaigns) },
    { label: t("sent"), value: String(data.total_sent) },
    { label: t("opened"), value: String(data.total_opened) },
    { label: t("replied"), value: String(data.total_replied) },
    { label: t("openRate"), value: pct(data.open_rate) },
    { label: t("replyRate"), value: pct(data.reply_rate) },
    { label: t("bounceRate"), value: pct(data.bounce_rate) },
    { label: t("pendingApprovals"), value: String(data.pending_approvals) },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      {!hasActivity ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          {tiles.map((tile) => (
            <div key={tile.label} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
              <p className="text-sm text-gray-500">{tile.label}</p>
              <p className="tabular mt-1 text-2xl font-bold text-gray-900">{tile.value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}
