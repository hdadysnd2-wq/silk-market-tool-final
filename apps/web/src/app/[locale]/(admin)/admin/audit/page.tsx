"use client";

import { useMemo, useState } from "react";
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

const PAGE_SIZE = 50;

export default function AdminAuditPage() {
  const t = useTranslations("admin");
  const { data: factories } = useApi<Factory[]>("/admin/factories");
  const [action, setAction] = useState("");
  const [factoryId, setFactoryId] = useState("");
  const [page, setPage] = useState(0);

  const path = useMemo(() => {
    const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
    if (action.trim()) q.set("action", action.trim());
    if (factoryId) q.set("factory_id", factoryId);
    return `/admin/audit?${q.toString()}`;
  }, [action, factoryId, page]);

  const { data, loading } = useApi<AuditEntry[]>(path);
  const rows = data ?? [];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("audit")}</h1>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          value={action}
          onChange={(e) => {
            setPage(0);
            setAction(e.target.value);
          }}
          placeholder={t("filterAction")}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        />
        <select
          value={factoryId}
          onChange={(e) => {
            setPage(0);
            setFactoryId(e.target.value);
          }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        >
          <option value="">{t("allFactories")}</option>
          {(factories ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {f.name_en}
            </option>
          ))}
        </select>
      </div>

      <ul className="mt-4 space-y-1">
        {rows.map((e) => (
          <li
            key={e.id}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg bg-white p-2 text-xs shadow-sm ring-1 ring-black/5"
          >
            {/* flex + gap + dir isolation: these are LTR tokens (action slugs,
                emails, dates) that would otherwise jumble inside the RTL row. */}
            <span className="font-medium text-gray-800" dir="ltr">
              {e.action}
            </span>
            <span className="text-gray-400" dir="ltr">
              {e.entity_type}
            </span>
            <span className="text-gray-400" dir="ltr">
              {e.actor_label}
            </span>
            <span className="text-gray-300" dir="ltr">
              {new Date(e.occurred_at).toLocaleString()}
            </span>
          </li>
        ))}
        {!loading && rows.length === 0 && <p className="text-sm text-gray-400">{t("empty")}</p>}
      </ul>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          disabled={page === 0}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40"
        >
          {t("prev")}
        </button>
        <span className="text-sm text-gray-500">{t("page", { n: page + 1 })}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={rows.length < PAGE_SIZE}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40"
        >
          {t("next")}
        </button>
      </div>
    </div>
  );
}
