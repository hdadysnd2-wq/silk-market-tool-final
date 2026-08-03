"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";

/**
 * The EU Legitimate Interest Assessment gate (I8). Shown on the approval screen
 * when a campaign targets an EU market and no LIA is on file yet — the backend
 * blocks queueing such a send (HTTP 412) until one is recorded, so this is the
 * way past that gate rather than a dead end.
 */
export function EuLiaGate({
  campaignId,
  onRecorded,
}: {
  campaignId: string;
  onRecorded: () => void;
}) {
  const t = useTranslations("campaign.lia");
  const [purpose, setPurpose] = useState("");
  const [necessity, setNecessity] = useState("");
  const [balancing, setBalancing] = useState("");
  const [sources, setSources] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = purpose.trim() !== "" && necessity.trim() !== "" && balancing.trim() !== "";

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${campaignId}/lia`, {
        purpose_text: purpose,
        necessity_text: necessity,
        balancing_test_text: balancing,
        data_sources: sources || null,
      });
      onRecorded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
      <h2 className="text-sm font-bold text-amber-900">{t("title")}</h2>
      <p className="mt-1 text-sm text-amber-800">{t("explain")}</p>

      <div className="mt-3 space-y-3">
        <Field label={t("purpose")} value={purpose} onChange={setPurpose} />
        <Field label={t("necessity")} value={necessity} onChange={setNecessity} />
        <Field label={t("balancing")} value={balancing} onChange={setBalancing} />
        <Field label={t("dataSources")} value={sources} onChange={setSources} />
      </div>

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <button
        onClick={submit}
        disabled={busy || !ready}
        className="mt-3 rounded-lg bg-amber-700 px-4 py-2 text-sm font-medium text-white hover:bg-amber-800 disabled:opacity-60"
      >
        {t("submit")}
      </button>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-amber-900">{label}</span>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        className="mt-1 w-full rounded-lg border border-amber-300 bg-white px-2 py-1.5 text-sm text-start"
      />
    </label>
  );
}
