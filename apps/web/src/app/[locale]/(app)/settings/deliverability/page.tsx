"use client";

import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

export default function DeliverabilityPage() {
  const t = useTranslations("deliverability");
  const { data: factory, reload } = useApi<Factory>("/factory");

  if (!factory) return <p className="text-gray-400">…</p>;

  async function toggle(field: "spf_ok" | "dkim_ok" | "dmarc_ok", value: boolean) {
    await api.put("/factory/deliverability", { [field]: value });
    reload();
  }

  async function startWarmup() {
    await api.put("/factory/deliverability", { start_warmup: true });
    reload();
  }

  const dnsRows: { key: "spf_ok" | "dkim_ok" | "dmarc_ok"; label: string; ok: boolean }[] = [
    { key: "spf_ok", label: t("spf"), ok: factory.spf_ok },
    { key: "dkim_ok", label: t("dkim"), ok: factory.dkim_ok },
    { key: "dmarc_ok", label: t("dmarc"), ok: factory.dmarc_ok },
  ];

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{t("note")}</p>

      <div className="mt-6 rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
        <p className="text-sm text-gray-500">{t("sendingDomain")}</p>
        <p className="font-medium text-gray-900" dir="ltr">
          {factory.sending_domain ?? "—"}
        </p>

        <ul className="mt-4 space-y-2">
          {dnsRows.map((row) => (
            <li key={row.key} className="flex items-center justify-between">
              <span className="text-sm text-gray-700">{row.label}</span>
              <button
                onClick={() => toggle(row.key, !row.ok)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  row.ok ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                }`}
              >
                {row.ok ? t("verified") : t("notVerified")}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-4 rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500">{t("warmup")}</p>
            <p className="tabular font-medium text-gray-900">
              {t("warmupDay")}: {factory.warmup_day}
            </p>
          </div>
          {factory.warmup_day === 0 && (
            <button
              onClick={startWarmup}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              {t("startWarmup")}
            </button>
          )}
        </div>
        <p className="tabular mt-2 text-xs text-gray-400">
          {t("dailyCap")}: {Math.min(50, Math.max(5, factory.warmup_day * 5))} · {t("dailyCap")}{" "}
          {factory.daily_send_count}
        </p>
      </div>
    </div>
  );
}
