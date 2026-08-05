"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

interface AdminCampaign {
  id: string;
  name: string;
  factory_id: string;
  factory_name_en: string;
  factory_name_ar: string;
  market_iso2: string;
  status: string;
  paused_reason: string | null;
  prepared_by_staff: boolean;
  total_emails: number;
  sent_count: number;
  opened_count: number;
  replied_count: number;
  bounced_count: number;
  complained_count: number;
  pending_approvals: number;
  created_at: string;
}

const STATUSES = ["draft", "active", "paused", "auto_paused", "completed"] as const;

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  active: "bg-green-100 text-green-700",
  paused: "bg-amber-50 text-amber-700",
  auto_paused: "bg-red-100 text-red-700",
  completed: "bg-blue-50 text-blue-700",
};

export default function AdminCampaignsPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const { data: factories } = useApi<Factory[]>("/admin/factories");
  const [status, setStatus] = useState("");
  const [factoryId, setFactoryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const path = useMemo(() => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (factoryId) q.set("factory_id", factoryId);
    const qs = q.toString();
    return `/admin/campaigns${qs ? `?${qs}` : ""}`;
  }, [status, factoryId]);

  const { data, loading, reload } = useApi<AdminCampaign[]>(path);
  const rows = data ?? [];

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("actionError"));
    } finally {
      setBusy(false);
    }
  }

  function pause(c: AdminCampaign) {
    const reason = prompt(t("pauseReasonPrompt"));
    if (reason === null) return; // cancelled
    act(() => api.post(`/admin/campaigns/${c.id}/pause?reason=${encodeURIComponent(reason || "—")}`));
  }

  function resume(c: AdminCampaign) {
    if (!confirm(t("confirmResume"))) return;
    act(() => api.post(`/admin/campaigns/${c.id}/resume`));
  }

  const factoryName = (c: AdminCampaign) => (locale === "ar" ? c.factory_name_ar : c.factory_name_en);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("campaigns")}</h1>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-4 flex flex-wrap gap-2">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        >
          <option value="">{t("allStatuses")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status_${s}`)}
            </option>
          ))}
        </select>
        <select
          value={factoryId}
          onChange={(e) => setFactoryId(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        >
          <option value="">{t("allFactories")}</option>
          {(factories ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {locale === "ar" ? f.name_ar : f.name_en}
            </option>
          ))}
        </select>
      </div>

      <ul className="mt-6 space-y-2">
        {rows.map((c) => (
          <li key={c.id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium text-gray-900" dir="auto">
                  {c.name}
                </span>
                <span className="text-sm text-gray-400" dir="auto">
                  {factoryName(c)}
                </span>
                <span className="text-xs text-gray-400" dir="ltr">
                  {c.market_iso2}
                </span>
                {c.prepared_by_staff && (
                  <span className="rounded-full bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700">
                    {t("preparedByStaff")}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {c.pending_approvals > 0 && (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                    {t("pendingBadge", { n: c.pending_approvals })}
                  </span>
                )}
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[c.status] ?? "bg-gray-100 text-gray-600"}`}
                >
                  {t(`status_${c.status}`)}
                </span>
                {c.status === "active" ? (
                  <button
                    onClick={() => pause(c)}
                    disabled={busy}
                    className="rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
                  >
                    {t("pause")}
                  </button>
                ) : c.status === "paused" || c.status === "auto_paused" ? (
                  <button
                    onClick={() => resume(c)}
                    disabled={busy}
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                  >
                    {t("resume")}
                  </button>
                ) : null}
              </div>
            </div>
            <p className="mt-2 text-sm text-gray-500">
              {t("statSent")}: <span className="tabular font-medium">{c.sent_count}</span>
              <span className="mx-2">·</span>
              {t("totalEmails")}: <span className="tabular font-medium">{c.total_emails}</span>
              <span className="mx-2">·</span>
              {t("replied")}: <span className="tabular font-medium">{c.replied_count}</span>
              <span className="mx-2">·</span>
              {t("bounced")}: <span className="tabular font-medium">{c.bounced_count}</span>
            </p>
            {c.paused_reason && (
              <p className="mt-1 text-xs text-amber-700" dir="auto">
                {t("pausedReasonLabel")}: {c.paused_reason}
              </p>
            )}
          </li>
        ))}
        {!loading && rows.length === 0 && <p className="text-sm text-gray-400">{t("empty")}</p>}
      </ul>
    </div>
  );
}
