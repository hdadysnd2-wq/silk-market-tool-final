"use client";

import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";

interface AuditEntry {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_label: string | null;
  occurred_at: string;
}

export default function AdminAuditPage() {
  const t = useTranslations("admin");
  const { data } = useApi<AuditEntry[]>("/admin/audit");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("audit")}</h1>
      <ul className="mt-6 space-y-1">
        {(data ?? []).map((e) => (
          <li key={e.id} className="rounded-lg bg-white p-2 text-xs shadow-sm ring-1 ring-black/5">
            <span className="font-medium text-gray-800">{e.action}</span>
            <span className="ms-2 text-gray-400">{e.entity_type}</span>
            <span className="ms-2 text-gray-400">{e.actor_label}</span>
            <span className="ms-2 text-gray-300">{new Date(e.occurred_at).toLocaleString()}</span>
          </li>
        ))}
        {data && data.length === 0 && <p className="text-sm text-gray-400">{t("empty")}</p>}
      </ul>
    </div>
  );
}
