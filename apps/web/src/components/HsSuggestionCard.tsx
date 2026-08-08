"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { HSCodeResult, Product } from "@/lib/types";

export function HsSuggestionCard({
  product,
  onConfirmed,
}: {
  product: Product;
  onConfirmed: () => void;
}) {
  const t = useTranslations("products");
  const locale = useLocale();
  const [selected, setSelected] = useState(product.hs_code ?? "");
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HSCodeResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidates = product.hs_candidates ?? [];
  const failed = product.classification_status === "failed";

  async function confirmCode(code: string) {
    if (!code) return;
    setBusy(true);
    setError(null);
    try {
      await api.put(`/products/${product.id}/hs-code`, { hs_code: code });
      onConfirmed();
    } catch {
      setError(t("hsConfirmError"));
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    const q = query.trim();
    if (q.length < 2) return;
    setSearching(true);
    try {
      setResults(await api.get<HSCodeResult[]>(`/hs-codes/search?q=${encodeURIComponent(q)}`));
    } finally {
      setSearching(false);
    }
  }

  async function retry() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/products/${product.id}/classify`);
      onConfirmed();
    } catch {
      setError(t("hsRetryError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
      <h3 className="font-semibold text-gray-900">{t("hsSuggestions")}</h3>

      {product.hs_auto_classified && product.hs_code && (
        <div className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
          {t("hsAutoCommitted", { code: product.hs_code })}
        </div>
      )}

      {failed && (
        <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          <p className="font-medium">{t("hsFailedTitle")}</p>
          <p className="mt-1">{product.failure_reason || t("hsFailedBody")}</p>
          <button
            onClick={retry}
            disabled={busy}
            className="mt-3 rounded-lg border border-amber-600 px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
          >
            {t("hsRetry")}
          </button>
        </div>
      )}

      {candidates.length > 0 && (
        <ul className="mt-3 space-y-2">
          {candidates.map((c) => {
            const active = selected === c.code;
            const description = locale === "ar" ? c.description_ar : c.description_en;
            return (
              <li key={c.code}>
                <button
                  onClick={() => setSelected(c.code)}
                  className={`flex w-full items-center gap-3 rounded-lg border p-3 text-start ${
                    active ? "border-brand-500 bg-brand-50" : "border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  <span className="tabular font-mono text-sm font-bold text-brand-700">
                    {c.code}
                  </span>
                  <span className="flex-1 text-sm text-gray-600">
                    {description ?? c.rationale}
                  </span>
                  <span className="tabular text-xs text-gray-400">
                    {Math.round(c.confidence * 100)}%
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {candidates.length > 0 && (
        <button
          onClick={() => confirmCode(selected)}
          disabled={busy || !selected}
          className="mt-4 w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {/* An auto-committed code (ADR-0009/0010) is already committed — the
              action is an override, exactly as after a human confirm. */}
          {product.hs_confirmed_by_user || (product.hs_auto_classified && product.hs_code)
            ? t("override")
            : t("confirm")}
        </button>
      )}

      {/* Manual fallback — always available, and the only path when classification
          proposed nothing. Search the catalogue by keyword, or type a known HS6. */}
      <div className="mt-4 border-t border-gray-100 pt-4">
        <p className="text-sm font-medium text-gray-700">{t("hsManualTitle")}</p>

        <div className="mt-2 flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder={t("hsSearchPlaceholder")}
            className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm"
          />
          <button
            onClick={search}
            disabled={searching || query.trim().length < 2}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("hsSearch")}
          </button>
        </div>

        {results.length > 0 && (
          <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
            {results.map((r) => (
              <li key={r.code}>
                <button
                  onClick={() => confirmCode(r.code)}
                  disabled={busy}
                  className="flex w-full items-center gap-3 rounded-lg border border-gray-200 p-2 text-start hover:bg-gray-50 disabled:opacity-60"
                >
                  <span className="tabular font-mono text-sm font-bold text-brand-700">
                    {r.code}
                  </span>
                  <span className="flex-1 text-sm text-gray-600">
                    {locale === "ar" ? r.description_ar : r.description_en}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex gap-2">
          <input
            value={manual}
            onChange={(e) => setManual(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder={t("hsManualPlaceholder")}
            inputMode="numeric"
            className="tabular flex-1 rounded-lg border border-gray-200 px-3 py-2 font-mono text-sm"
          />
          <button
            onClick={() => confirmCode(manual)}
            disabled={busy || manual.length !== 6}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("hsManualConfirm")}
          </button>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </div>
  );
}
