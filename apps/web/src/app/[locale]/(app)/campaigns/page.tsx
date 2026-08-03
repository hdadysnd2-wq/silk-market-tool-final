"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { useApi } from "@/lib/useApi";
import type { Campaign } from "@/lib/types";

export default function CampaignsPage() {
  const t = useTranslations("campaign");
  const nav = useTranslations("nav");
  const { data, loading } = useApi<Campaign[]>("/campaigns");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{nav("campaigns")}</h1>
      {loading ? (
        <p className="mt-6 text-gray-400">…</p>
      ) : !data || data.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {data.map((c) => (
            <li key={c.id}>
              <Link
                href={`/campaigns/${c.id}/review`}
                className="flex items-center justify-between rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5 hover:ring-brand-200"
              >
                <div>
                  <p className="font-medium text-gray-900">{c.name}</p>
                  <p className="text-sm text-gray-500">
                    {c.market_iso2} · {c.status}
                  </p>
                </div>
                <div className="tabular text-end text-sm text-gray-500">
                  <span className="text-brand-700">{c.sent_count}</span> / {c.total_emails}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
