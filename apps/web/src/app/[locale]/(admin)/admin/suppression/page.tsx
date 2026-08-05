"use client";

import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";

interface SuppressionRow {
  email: string;
  reason: string;
  created_at: string;
}

export default function AdminSuppressionPage() {
  const t = useTranslations("admin");
  const { data } = useApi<SuppressionRow[]>("/admin/suppression");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("suppression")}</h1>
      <ul className="mt-6 space-y-1">
        {(data ?? []).map((row) => (
          <li
            key={row.email}
            className="rounded-lg bg-white p-2 text-sm shadow-sm ring-1 ring-black/5"
          >
            <span dir="ltr" className="text-gray-800">
              {row.email}
            </span>
            <span className="ms-2 text-xs text-gray-400">{row.reason}</span>
          </li>
        ))}
        {data && data.length === 0 && <p className="text-sm text-gray-400">{t("empty")}</p>}
      </ul>
    </div>
  );
}
