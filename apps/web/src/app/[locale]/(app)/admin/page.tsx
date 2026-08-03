"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

interface AuditEntry {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_label: string | null;
  occurred_at: string;
}

interface SuppressionRow {
  email: string;
  reason: string;
  created_at: string;
}

export default function AdminPage() {
  const nav = useTranslations("nav");
  const [tab, setTab] = useState<"factories" | "suppression" | "audit">("factories");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{nav("admin")}</h1>
      <div className="mt-4 flex gap-2 border-b border-gray-200">
        {(["factories", "suppression", "audit"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-2 text-sm ${
              tab === k ? "border-b-2 border-brand-600 font-medium text-brand-700" : "text-gray-500"
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === "factories" && <FactoriesTab />}
        {tab === "suppression" && <SuppressionTab />}
        {tab === "audit" && <AuditTab />}
      </div>
    </div>
  );
}

function FactoriesTab() {
  const { data } = useApi<Factory[]>("/admin/factories");
  return (
    <ul className="space-y-2">
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
            DNS
          </span>
        </li>
      ))}
    </ul>
  );
}

function SuppressionTab() {
  const { data } = useApi<SuppressionRow[]>("/admin/suppression");
  return (
    <ul className="space-y-1">
      {(data ?? []).map((row) => (
        <li key={row.email} className="rounded-lg bg-white p-2 text-sm shadow-sm ring-1 ring-black/5">
          <span dir="ltr" className="text-gray-800">
            {row.email}
          </span>
          <span className="ms-2 text-xs text-gray-400">{row.reason}</span>
        </li>
      ))}
      {data && data.length === 0 && <p className="text-sm text-gray-400">—</p>}
    </ul>
  );
}

function AuditTab() {
  const { data } = useApi<AuditEntry[]>("/admin/audit");
  return (
    <ul className="space-y-1">
      {(data ?? []).map((e) => (
        <li key={e.id} className="rounded-lg bg-white p-2 text-xs shadow-sm ring-1 ring-black/5">
          <span className="font-medium text-gray-800">{e.action}</span>
          <span className="ms-2 text-gray-400">{e.entity_type}</span>
          <span className="ms-2 text-gray-400">{e.actor_label}</span>
          <span className="ms-2 text-gray-300">{new Date(e.occurred_at).toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}
