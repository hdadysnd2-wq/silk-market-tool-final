"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Product } from "@/lib/types";

export default function ProductsPage() {
  const t = useTranslations("products");
  const { data, loading, reload } = useApi<Product[]>("/products");
  const [open, setOpen] = useState(false);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        <button
          onClick={() => setOpen(true)}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {t("upload")}
        </button>
      </div>

      {loading ? (
        <p className="mt-6 text-gray-400">…</p>
      ) : !data || data.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("empty")}
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {data.map((p) => (
            <li key={p.id}>
              <Link
                href={`/products/${p.id}`}
                className="flex items-center justify-between rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5 hover:ring-brand-200"
              >
                <div>
                  <p className="font-medium text-gray-900">{p.name_en}</p>
                  <p className="text-sm text-gray-500">{p.name_ar}</p>
                </div>
                <div className="text-end">
                  <span className="tabular text-sm font-medium text-brand-700">
                    {p.hs_code ?? "—"}
                  </span>
                  <p className="text-xs text-gray-400">
                    {p.classification_status === "classified" ? t("classified") : t("pending")}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <UploadDialog
          onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false);
            reload();
          }}
        />
      )}
    </div>
  );
}

function UploadDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const t = useTranslations("products");
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const form = new FormData(e.currentTarget);
    if (file) form.set("image", file);
    else form.delete("image");
    try {
      await api.post("/products", form);
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-black/30 px-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg space-y-3 rounded-2xl bg-white p-6 shadow-lg"
      >
        <h2 className="text-lg font-bold text-gray-900">{t("upload")}</h2>
        <div className="grid grid-cols-2 gap-3">
          <Input name="name_ar" label={t("nameAr")} required />
          <Input name="name_en" label={t("nameEn")} required />
        </div>
        <Input name="description_en" label={t("descriptionEn")} />
        <div className="grid grid-cols-2 gap-3">
          <Input name="price_min" label={t("priceMin")} type="number" />
          <Input name="price_max" label={t("priceMax")} type="number" />
        </div>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("image")}</span>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-gray-600">
            {t("nameAr") && "×"}
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("createProduct")}
          </button>
        </div>
      </form>
    </div>
  );
}

function Input({
  name,
  label,
  type = "text",
  required,
}: {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        name={name}
        type={type}
        required={required}
        step={type === "number" ? "any" : undefined}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
      />
    </label>
  );
}
