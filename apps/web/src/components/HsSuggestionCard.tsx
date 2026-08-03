"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Product } from "@/lib/types";

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

  async function confirm() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.put(`/products/${product.id}/hs-code`, { hs_code: selected });
      onConfirmed();
    } finally {
      setBusy(false);
    }
  }

  const candidates = product.hs_candidates ?? [];

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
      <h3 className="font-semibold text-gray-900">{t("hsSuggestions")}</h3>
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
                <span className="tabular font-mono text-sm font-bold text-brand-700">{c.code}</span>
                <span className="flex-1 text-sm text-gray-600">{description ?? c.rationale}</span>
                <span className="tabular text-xs text-gray-400">
                  {Math.round(c.confidence * 100)}%
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <button
        onClick={confirm}
        disabled={busy || !selected}
        className="mt-4 w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
      >
        {product.hs_confirmed_by_user ? t("override") : t("confirm")}
      </button>
    </div>
  );
}
