"use client";

import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

export default function AdminFactoriesPage() {
  const t = useTranslations("admin");
  const { data } = useApi<Factory[]>("/admin/factories");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("factories")}</h1>
      <ul className="mt-6 space-y-2">
        {(data ?? []).map((f) => (
          <li key={f.id} className="rounded-lg bg-white p-3 text-sm shadow-sm ring-1 ring-black/5">
            <span className="font-medium text-gray-900">{f.name_en}</span>
            <span className="ms-2 text-gray-400">{f.sector}</span>
            <span className="ms-2 text-xs text-gray-400" dir="ltr">
              {f.sending_domain}
            </span>
            <span
              className={`ms-2 rounded-full px-2 py-0.5 text-xs ${
                f.spf_ok && f.dkim_ok && f.dmarc_ok
                  ? "bg-green-100 text-green-700"
                  : "bg-amber-50 text-amber-700"
              }`}
            >
              {t("dns")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
