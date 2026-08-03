"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { useApi } from "@/lib/useApi";
import type { DashboardStats } from "@/lib/types";

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const { data, loading } = useApi<DashboardStats>("/dashboard");

  if (loading) return <p className="text-gray-400">…</p>;
  if (!data) return null;

  const hasActivity = data.campaigns > 0;

  const tiles: { label: string; value: string; href?: string; hint?: string }[] = [
    { label: t("campaigns"), value: String(data.campaigns) },
    { label: t("sent"), value: String(data.total_sent) },
    { label: t("opened"), value: String(data.total_opened) },
    { label: t("replied"), value: String(data.total_replied) },
    { label: t("openRate"), value: pct(data.open_rate) },
    { label: t("replyRate"), value: pct(data.reply_rate) },
    { label: t("bounceRate"), value: pct(data.bounce_rate) },
    {
      label: t("pendingApprovals"),
      value: String(data.pending_approvals),
      // The approval gate lives on each campaign's review screen; when drafts
      // are waiting, make the count a way in rather than a dead number.
      href: data.pending_approvals > 0 ? "/campaigns" : undefined,
      hint: data.pending_approvals > 0 ? t("reviewPending") : undefined,
    },
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
          {tiles.map((tile) => {
            const body = (
              <>
                <p className="text-sm text-gray-500">{tile.label}</p>
                <p className="tabular mt-1 text-2xl font-bold text-gray-900">{tile.value}</p>
                {tile.hint && (
                  <p className="mt-1 text-xs font-medium text-brand-600">{tile.hint} →</p>
                )}
              </>
            );
            return tile.href ? (
              <Link
                key={tile.label}
                href={tile.href}
                className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5 hover:ring-brand-200"
              >
                {body}
              </Link>
            ) : (
              <div key={tile.label} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
                {body}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}
