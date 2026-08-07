"use client";

import { useTranslations } from "next-intl";
import { ErrorNotice } from "@/components/ErrorNotice";
import { Link } from "@/i18n/routing";
import { useApi } from "@/lib/useApi";
import type { DashboardStats, SenderAccount } from "@/lib/types";

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const { data, loading, error, reload } = useApi<DashboardStats>("/dashboard");
  const { data: senders } = useApi<SenderAccount[]>("/sender-accounts");

  if (loading) return <p className="text-gray-400">…</p>;
  // A failed load used to return null — a blank page indistinguishable from
  // "no data" (audit). Surface the error with a retry instead.
  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return null;

  const hasActivity = data.campaigns > 0;
  // A factory can't send until at least one mailbox is connected AND verified.
  // Until then, surface a callout that routes straight to the connect flow.
  const needsSender = senders !== null && !senders.some((s) => s.verification_status === "verified");

  // No open-rate tile (audit 2026-08-07 C7): opens are webhook-only, and the
  // production mailbox path has no open tracking — the rate would honestly
  // read ~0% and look broken. Replies and bounces ARE tracked on every path.
  const tiles: { label: string; value: string; href?: string; hint?: string }[] = [
    { label: t("campaigns"), value: String(data.campaigns) },
    { label: t("sent"), value: String(data.total_sent) },
    { label: t("replied"), value: String(data.total_replied) },
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

      {needsSender && (
        <div className="mt-6 flex flex-col gap-3 rounded-xl bg-amber-50 p-5 ring-1 ring-amber-200 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium text-amber-900">{t("noSenderTitle")}</p>
            <p className="mt-1 text-sm text-amber-800">{t("noSenderBody")}</p>
          </div>
          <Link
            href="/settings/sending-email"
            className="shrink-0 rounded-lg bg-brand-600 px-4 py-2 text-center text-sm font-medium text-white hover:bg-brand-700"
          >
            {t("noSenderCta")}
          </Link>
        </div>
      )}

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
