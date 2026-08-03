"use client";

import { use, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { CompetitorSnapshot } from "@/components/CompetitorSnapshot";
import type { CompetitorSnapshot as Snapshot, Market, Product } from "@/lib/types";

export default function MarketsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("markets");
  const locale = useLocale();
  const router = useRouter();
  const { data: product } = useApi<Product>(`/products/${id}`);
  const { data: markets } = useApi<Market[]>("/markets");
  const [selected, setSelected] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [starting, setStarting] = useState(false);

  async function pick(iso2: string) {
    setSelected(iso2);
    setSnapshot(null);
    if (product?.hs_code) {
      const snap = await api.get<Snapshot>(
        `/markets/${iso2}/competitors?hs_code=${product.hs_code}`,
      );
      setSnapshot(snap);
    }
  }

  async function discover() {
    if (!selected) return;
    setStarting(true);
    try {
      await api.post(`/products/${id}/discover`, { markets: [selected] });
      router.push(`/products/${id}/buyers?market=${selected}`);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <div className="flex flex-wrap gap-2">
          {(markets ?? []).map((m) => (
            <button
              key={m.iso2}
              onClick={() => pick(m.iso2)}
              className={`rounded-lg border px-3 py-2 text-sm ${
                selected === m.iso2
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {locale === "ar" ? m.name_ar : m.name_en}
              {m.is_eu && <span className="ms-1 text-xs text-amber-600">EU</span>}
            </button>
          ))}
        </div>

        <div>
          {snapshot && <CompetitorSnapshot snapshot={snapshot} />}
          {selected && (
            <button
              onClick={discover}
              disabled={starting}
              className="mt-4 w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {t("select")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
