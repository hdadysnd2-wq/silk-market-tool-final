"use client";

import { use, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { BuyerCard } from "@/components/BuyerCard";
import type { BuyerMatch, Campaign, SenderAccount } from "@/lib/types";

export default function BuyersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("buyers");
  const router = useRouter();
  const search = useSearchParams();
  const paramMarket = search.get("market");

  // Poll while discovery runs in the background worker.
  const query = paramMarket
    ? `/products/${id}/buyers?market=${paramMarket}`
    : `/products/${id}/buyers`;
  const { data, loading } = useApi<BuyerMatch[]>(query, 4000);
  // A verified connected mailbox is a hard prerequisite for creating a campaign
  // (also enforced server-side on POST /campaigns).
  const { data: senders } = useApi<SenderAccount[]>("/sender-accounts");
  const hasVerifiedSender = (senders ?? []).some(
    (s) => s.verification_status === "verified",
  );

  const buyers = data ?? [];

  // A campaign targets a single market, and its drafts are built only from the
  // buyers in that market. When the view is filtered (?market=…) that market is
  // implied. On the unfiltered "discover across the top markets" view the buyer
  // list can span several markets, so the user must choose which one to launch
  // outreach into — otherwise the create action has no market to act on.
  const marketsInList = useMemo(() => {
    const set = new Set<string>();
    for (const m of data ?? []) if (m.market_iso2) set.add(m.market_iso2);
    return [...set].sort();
  }, [data]);
  const [picked, setPicked] = useState<string | null>(null);
  const effectiveMarket = paramMarket ?? picked ?? marketsInList[0] ?? null;
  const showMarketPicker = !paramMarket && marketsInList.length > 1;

  const [creating, setCreating] = useState(false);

  async function createCampaign() {
    if (!effectiveMarket || !hasVerifiedSender) return;
    setCreating(true);
    try {
      const campaign = await api.post<Campaign>("/campaigns", {
        product_id: id,
        market_iso2: effectiveMarket,
        name: `Outreach → ${effectiveMarket}`,
      });
      await api.post(`/campaigns/${campaign.id}/draft`);
      router.push(`/campaigns/${campaign.id}/review`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        {buyers.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/products/${id}/report`}
              className="rounded-lg border border-brand-600 px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-50"
            >
              {t("viewReport")}
            </Link>
            {hasVerifiedSender ? (
              <>
                {showMarketPicker && (
                  <select
                    aria-label={t("campaignMarket")}
                    value={effectiveMarket ?? ""}
                    onChange={(e) => setPicked(e.target.value)}
                    className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
                  >
                    {marketsInList.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                )}
                <button
                  onClick={createCampaign}
                  disabled={creating || !effectiveMarket}
                  className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
                >
                  {t("createCampaign")}
                </button>
              </>
            ) : (
              <Link
                href="/onboarding/email"
                className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
              >
                {t("connectEmailCta")}
              </Link>
            )}
          </div>
        )}
      </div>

      {buyers.length > 0 && !hasVerifiedSender && (
        <p className="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200">
          {t("senderRequired")}
        </p>
      )}

      {loading && buyers.length === 0 ? (
        <p className="mt-6 text-gray-400">…</p>
      ) : buyers.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {buyers.map((m) => (
            <li key={m.buyer.id}>
              <BuyerCard match={m} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
