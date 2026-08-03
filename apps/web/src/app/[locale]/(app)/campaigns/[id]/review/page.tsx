"use client";

import { use } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { EmailReviewSplitView } from "@/components/EmailReviewSplitView";
import type { BuyerMatch, Campaign, Email, EmailStatus } from "@/lib/types";

// Which statuses roll up into each approval-gate bucket. `draft` still needs a
// human; `approved`/`queued` have cleared the I3 gate and are on their way out;
// the rest are post-send outcomes.
const APPROVED_STATUSES: EmailStatus[] = ["approved", "queued"];
const SENT_STATUSES: EmailStatus[] = [
  "sent",
  "opened",
  "replied",
  "bounced",
  "complained",
];

export default function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("campaign");
  const { data: campaign } = useApi<Campaign>(`/campaigns/${id}`);
  // Poll: drafting runs in the worker, and statuses advance as sends/opens land.
  const { data: emails, loading, reload } = useApi<Email[]>(
    `/campaigns/${id}/emails`,
    5000,
  );
  const { data: buyerMatches } = useApi<BuyerMatch[]>(
    campaign ? `/products/${campaign.product_id}/buyers?market=${campaign.market_iso2}` : null,
  );

  const buyerById = new Map((buyerMatches ?? []).map((m) => [m.buyer.id, m]));
  const list = emails ?? [];

  // The approval-gate summary, derived from the drafts themselves — how many
  // still need the operator's review vs. have cleared it vs. have gone out.
  const pending = list.filter((e) => e.status === "draft").length;
  const approved = list.filter((e) => APPROVED_STATUSES.includes(e.status)).length;
  const sent = list.filter((e) => SENT_STATUSES.includes(e.status)).length;

  return (
    <div>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold text-gray-900">
            {campaign?.name ?? t("review")}
          </h1>
          {campaign && (
            <p className="mt-0.5 text-sm text-gray-500">
              {campaign.market_iso2} · {campaign.status}
            </p>
          )}
        </div>
        {list.length === 0 && (
          <button
            onClick={async () => {
              await api.post(`/campaigns/${id}/draft`);
              setTimeout(reload, 1500);
            }}
            className="shrink-0 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            {t("draftEmails")}
          </button>
        )}
      </div>

      {list.length > 0 && (
        <div
          role="group"
          aria-label={t("approvalSummary")}
          className="mt-4 flex flex-wrap gap-3"
        >
          <StatChip label={t("progressPending")} value={pending} tone="amber" />
          <StatChip label={t("progressApproved")} value={approved} tone="blue" />
          <StatChip label={t("progressSent")} value={sent} tone="brand" />
        </div>
      )}

      <p className="mt-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">
        {t("noApprovalWithoutReview")}
      </p>

      {loading && list.length === 0 ? (
        <p className="mt-6 text-gray-400">…</p>
      ) : list.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <ul className="mt-6 space-y-4">
          {list.map((email) => (
            <li key={email.id}>
              <EmailReviewSplitView
                email={email}
                buyer={buyerById.get(email.buyer_id)}
                onChanged={reload}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const TONES: Record<string, string> = {
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
};

function StatChip({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`rounded-lg px-3 py-1.5 text-sm ring-1 ${TONES[tone] ?? TONES.blue}`}>
      <span className="tabular font-bold">{value}</span> <span>{label}</span>
    </div>
  );
}
