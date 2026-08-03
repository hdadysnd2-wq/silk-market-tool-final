"use client";

import { use } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { EmailReviewSplitView } from "@/components/EmailReviewSplitView";
import type { BuyerMatch, Campaign, Email } from "@/lib/types";

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

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("review")}</h1>
        {list.length === 0 && (
          <button
            onClick={async () => {
              await api.post(`/campaigns/${id}/draft`);
              setTimeout(reload, 1500);
            }}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            {t("draftEmails")}
          </button>
        )}
      </div>

      <p className="mt-2 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">
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
