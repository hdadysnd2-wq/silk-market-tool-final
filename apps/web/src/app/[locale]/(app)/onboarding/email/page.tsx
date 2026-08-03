"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { SenderAccount } from "@/lib/types";

const STATUS_STYLES: Record<SenderAccount["verification_status"], string> = {
  verified: "bg-green-100 text-green-700",
  pending: "bg-amber-100 text-amber-700",
  needs_reauth: "bg-red-100 text-red-700",
  disabled: "bg-gray-100 text-gray-500",
};

export default function ConnectEmailPage() {
  const t = useTranslations("emailConnect");
  const search = useSearchParams();
  const { data, loading, reload } = useApi<SenderAccount[]>("/sender-accounts");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connected = search.get("connected");
  const connectError = search.get("error");
  const connectedEmail = search.get("email");

  async function start(path: string) {
    setBusy(path);
    setError(null);
    try {
      const res = await api.post<{ authorization_url: string }>(path);
      // Full-page redirect into the provider consent flow.
      window.location.href = res.authorization_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errorBanner"));
      setBusy(null);
    }
  }

  async function disconnect(id: string) {
    setBusy(id);
    setError(null);
    try {
      await api.del(`/sender-accounts/${id}`);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errorBanner"));
    } finally {
      setBusy(null);
    }
  }

  const accounts = data ?? [];

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mt-2 text-sm text-gray-500">{t("subtitle")}</p>

      {connected && (
        <div className="mt-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200">
          {t("connectedBanner", { email: connectedEmail ?? "" })}
        </div>
      )}
      {connectError && (
        <div className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
          {t("errorBanner")}
        </div>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {/* Connect buttons */}
      <div className="mt-6 rounded-xl bg-white p-6 shadow-sm ring-1 ring-black/5">
        <p className="text-sm font-medium text-gray-500">{t("addMailbox")}</p>
        <div className="mt-3 flex flex-wrap gap-3">
          <button
            onClick={() => start("/sender-accounts/connect/gmail")}
            disabled={busy !== null}
            className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("connectGoogle")}
          </button>
          <button
            onClick={() => start("/sender-accounts/connect/microsoft")}
            disabled={busy !== null}
            className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("connectMicrosoft")}
          </button>
        </div>
      </div>

      {/* Scope explanation */}
      <div className="mt-4 rounded-xl bg-white p-6 shadow-sm ring-1 ring-black/5">
        <p className="text-sm font-medium text-gray-900">{t("scopesTitle")}</p>
        <ul className="mt-3 space-y-2 text-sm text-gray-600">
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-brand-600">✓</span>
            {t("scopeSend")}
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-brand-600">✓</span>
            {t("scopeRead")}
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-gray-400">•</span>
            {t("scopeNothingElse")}
          </li>
        </ul>
      </div>

      {/* Connected mailboxes */}
      <h2 className="mt-8 text-sm font-medium text-gray-500">{t("connectedMailboxes")}</h2>
      {loading ? (
        <p className="mt-3 text-gray-400">…</p>
      ) : accounts.length === 0 ? (
        <p className="mt-3 rounded-xl bg-white p-6 text-center text-gray-500 ring-1 ring-black/5">
          {t("noMailboxes")}
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {accounts.map((a) => (
            <li
              key={a.id}
              className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-gray-900" dir="ltr">
                    {a.email}
                  </p>
                  <p className="text-xs text-gray-500">
                    {a.provider_type} · {t("warmupStage", { stage: a.warmup_stage })} ·{" "}
                    <span className="tabular">
                      {t("dailyUsage", { sent: a.daily_sent_count, limit: a.daily_send_limit })}
                    </span>
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${STATUS_STYLES[a.verification_status]}`}
                >
                  {t(`status.${a.verification_status}`)}
                </span>
              </div>

              {a.verification_status === "needs_reauth" && (
                <p className="mt-2 text-xs text-red-600">
                  {t("reauthBanner", { email: a.email })}
                </p>
              )}

              <div className="mt-3 flex gap-2">
                {(a.verification_status === "needs_reauth" ||
                  a.verification_status === "disabled") && (
                  <button
                    onClick={() => start(`/sender-accounts/${a.id}/reconnect`)}
                    disabled={busy !== null}
                    className="rounded-lg border border-brand-600 px-3 py-1.5 text-sm text-brand-700 hover:bg-brand-50 disabled:opacity-60"
                  >
                    {t("reconnect")}
                  </button>
                )}
                {a.verification_status !== "disabled" && (
                  <button
                    onClick={() => disconnect(a.id)}
                    disabled={busy !== null}
                    className="rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
                  >
                    {t("disconnect")}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-8">
        <Link
          href="/dashboard"
          className="text-sm font-medium text-brand-700 hover:text-brand-800"
        >
          {t("continue")} →
        </Link>
      </div>
    </div>
  );
}
