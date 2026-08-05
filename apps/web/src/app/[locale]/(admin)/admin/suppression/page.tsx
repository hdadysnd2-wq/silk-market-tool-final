"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";

interface SuppressionRow {
  email: string;
  reason: string;
  note?: string | null;
  created_at: string;
}

export default function AdminSuppressionPage() {
  const t = useTranslations("admin");
  const { data, reload } = useApi<SuppressionRow[]>("/admin/suppression");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const q = new URLSearchParams({ email });
      if (note) q.set("note", note);
      await api.post(`/admin/suppression?${q.toString()}`);
      setEmail("");
      setNote("");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("actionError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("suppression")}</h1>

      <form
        onSubmit={submit}
        className="mt-4 flex flex-wrap items-end gap-2 rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5"
      >
        <label className="block flex-1">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("email")}</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            dir="ltr"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <label className="block flex-1">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("note")}</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {t("suppressAdd")}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <ul className="mt-4 space-y-1">
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
