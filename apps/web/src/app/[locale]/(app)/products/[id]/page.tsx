"use client";

import { use, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { useApi } from "@/lib/useApi";
import { HsSuggestionCard } from "@/components/HsSuggestionCard";
import type { Product } from "@/lib/types";

export default function ProductDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("products");
  // Classification runs async on a worker. Poll until it reaches a terminal
  // state so `HsSuggestionCard` (which reads `product.hs_candidates`) renders
  // once classification completes; stop polling once classified/failed.
  const [pollMs, setPollMs] = useState(2000);
  const { data: product, loading, reload } = useApi<Product>(`/products/${id}`, pollMs);

  useEffect(() => {
    if (!product) return;
    const terminal =
      product.classification_status === "classified" ||
      product.classification_status === "failed";
    setPollMs(terminal ? 0 : 2000);
  }, [product]);

  if (loading) return <p className="text-gray-400">…</p>;
  if (!product) return null;

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{product.name_en}</h1>
      <p className="text-gray-500">{product.name_ar}</p>
      {product.description_en && (
        <p className="mt-2 text-sm text-gray-600">{product.description_en}</p>
      )}

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <HsSuggestionCard product={product} onConfirmed={reload} />

        <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
          <p className="text-sm text-gray-500">{t("hsCode")}</p>
          <p className="tabular mt-1 text-2xl font-bold text-brand-700">
            {product.hs_code ?? "—"}
          </p>
          {product.hs_confirmed_by_user && product.hs_code && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                href={`/products/${product.id}/markets`}
                className="inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
              >
                {t("findBuyers")}
              </Link>
              <Link
                href={`/products/${product.id}/report`}
                className="inline-block rounded-lg border border-brand-600 px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-50"
              >
                {t("viewReport")}
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
