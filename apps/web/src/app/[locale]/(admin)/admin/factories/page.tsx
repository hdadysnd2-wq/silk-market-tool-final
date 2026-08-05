"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

interface FactoryOverview {
  factory: Factory;
  campaigns: number;
  pending_approvals: number;
}

export default function AdminFactoriesPage() {
  const t = useTranslations("admin");
  const { data, reload } = useApi<Factory[]>("/admin/factories");
  const [openId, setOpenId] = useState<string | null>(null);
  const [overview, setOverview] = useState<FactoryOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleDetails(f: Factory) {
    setError(null);
    if (openId === f.id) {
      setOpenId(null);
      setOverview(null);
      return;
    }
    setOpenId(f.id);
    setOverview(null);
    try {
      setOverview(await api.get<FactoryOverview>(`/admin/factories/${f.id}/overview`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("actionError"));
    }
  }

  async function act(f: Factory, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
      if (openId === f.id) {
        setOverview(await api.get<FactoryOverview>(`/admin/factories/${f.id}/overview`));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("actionError"));
    } finally {
      setBusy(false);
    }
  }

  function markDns(f: Factory) {
    if (!confirm(t("confirmMarkDns"))) return;
    act(f, () => api.post(`/admin/factories/${f.id}/deliverability/verify`));
  }

  function pause(f: Factory) {
    const reason = prompt(t("pauseReasonPrompt"));
    if (reason === null) return; // cancelled
    act(f, () =>
      api.post(`/admin/factories/${f.id}/pause?reason=${encodeURIComponent(reason || "—")}`),
    );
  }

  function resume(f: Factory) {
    if (!confirm(t("confirmResume"))) return;
    act(f, () => api.post(`/admin/factories/${f.id}/resume`));
  }

  const dnsOk = (f: Factory) => f.spf_ok && f.dkim_ok && f.dmarc_ok;

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("factories")}</h1>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      <ul className="mt-6 space-y-2">
        {(data ?? []).map((f) => (
          <li key={f.id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="font-medium text-gray-900">{f.name_en}</span>
                <span className="ms-2 text-sm text-gray-400">{f.sector}</span>
                <span className="ms-2 text-xs text-gray-400" dir="ltr">
                  {f.sending_domain}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    dnsOk(f) ? "bg-green-100 text-green-700" : "bg-amber-50 text-amber-700"
                  }`}
                >
                  {dnsOk(f) ? t("dnsVerified") : t("dnsUnverified")}
                </span>
                {f.sends_paused && (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                    {t("pausedStatus")}
                  </span>
                )}
                <button
                  onClick={() => toggleDetails(f)}
                  className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
                >
                  {t("details")}
                </button>
              </div>
            </div>

            {openId === f.id && (
              <div className="mt-3 border-t border-gray-100 pt-3">
                {overview ? (
                  <p className="text-sm text-gray-600">
                    {t("campaigns")}: <span className="tabular font-medium">{overview.campaigns}</span>
                    <span className="mx-2">·</span>
                    {t("statPending")}:{" "}
                    <span className="tabular font-medium">{overview.pending_approvals}</span>
                  </p>
                ) : (
                  <p className="text-sm text-gray-400">…</p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {!dnsOk(f) && (
                    <button
                      onClick={() => markDns(f)}
                      disabled={busy}
                      className="rounded-lg border border-brand-600 px-3 py-1.5 text-sm text-brand-700 hover:bg-brand-50 disabled:opacity-60"
                    >
                      {t("markDnsVerified")}
                    </button>
                  )}
                  {f.sends_paused ? (
                    <button
                      onClick={() => resume(f)}
                      disabled={busy}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                    >
                      {t("resume")}
                    </button>
                  ) : (
                    <button
                      onClick={() => pause(f)}
                      disabled={busy}
                      className="rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
                    >
                      {t("pause")}
                    </button>
                  )}
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
