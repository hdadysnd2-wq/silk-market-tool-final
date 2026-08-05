"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { useApi } from "@/lib/useApi";

interface InboxItem {
  email_id: string;
  campaign_id: string;
  campaign_name: string;
  market_iso2: string;
  buyer_name: string;
  contact_email: string;
  contact_name: string | null;
  subject: string;
  language: string;
  sent_at: string | null;
  replied_at: string | null;
}

export default function InboxPage() {
  const t = useTranslations("inbox");
  // Poll: replies land from the reply-detection beat / provider webhooks.
  const { data, loading } = useApi<InboxItem[]>("/inbox", 15000);
  const rows = data ?? [];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mt-1 text-sm text-gray-500">{t("subtitle")}</p>

      <ul className="mt-6 space-y-2">
        {rows.map((r) => (
          <li key={r.email_id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-medium text-gray-900" dir="ltr">
                  {r.buyer_name}
                </span>
                <span className="text-sm text-gray-400" dir="ltr">
                  {r.contact_name ? `${r.contact_name} · ` : ""}
                  {r.contact_email}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                  {t("repliedBadge")}
                </span>
                {r.replied_at && (
                  <span className="text-xs text-gray-400" dir="ltr">
                    {new Date(r.replied_at).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
            <p className="mt-2 text-sm text-gray-700" dir="auto">
              {r.subject}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-gray-400">
              <Link
                href={`/campaigns/${r.campaign_id}/review`}
                className="font-medium text-brand-600 hover:text-brand-700"
              >
                {r.campaign_name} →
              </Link>
              <span dir="ltr">{r.market_iso2}</span>
            </div>
          </li>
        ))}
        {!loading && rows.length === 0 && (
          <p className="rounded-xl bg-white p-8 text-center text-sm text-gray-500 ring-1 ring-black/5">
            {t("empty")}
          </p>
        )}
      </ul>

      {rows.length > 0 && <p className="mt-4 text-xs text-gray-400">{t("openMailboxHint")}</p>}
    </div>
  );
}
