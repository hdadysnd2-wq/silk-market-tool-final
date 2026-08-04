"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Product, ProductAccepted } from "@/lib/types";

export default function ProductsPage() {
  const t = useTranslations("products");
  // Classification runs async on a worker (202 + poll). While any product is
  // still `pending`, poll the list so a newly-created product flips to
  // `classified` without a manual refresh; stop once none are pending.
  const [pollMs, setPollMs] = useState(0);
  const { data, loading, reload } = useApi<Product[]>("/products", pollMs);
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState(false);

  useEffect(() => {
    const anyPending = (data ?? []).some((p) => p.classification_status === "pending");
    setPollMs(anyPending ? 2000 : 0);
  }, [data]);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
        <button
          onClick={() => {
            setNotice(false);
            setOpen(true);
          }}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {t("upload")}
        </button>
      </div>

      {notice && (
        <div
          role="status"
          className="mt-4 flex items-center justify-between rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200"
        >
          <span>{t("createSuccess")}</span>
          <button
            onClick={() => setNotice(false)}
            aria-label={t("close")}
            className="text-green-700 hover:text-green-900"
          >
            ✕
          </button>
        </div>
      )}

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
            setNotice(true);
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
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const form = new FormData(e.currentTarget);
    if (file) form.set("image", file);
    else form.delete("image");

    // Client-side guard: a min above the max is never valid, so catch it before
    // the round-trip. Blank fields are allowed (the backend coerces "" → unset).
    const min = form.get("price_min");
    const max = form.get("price_max");
    if (typeof min === "string" && min !== "" && typeof max === "string" && max !== "") {
      if (Number(min) > Number(max)) {
        setError(t("priceRangeError"));
        return;
      }
    }

    setBusy(true);
    try {
      // 202 Accepted: classification runs on a worker. The list poll (above)
      // reflects pending → classified once the entity's status flips.
      await api.post<ProductAccepted>("/products", form);
      onCreated();
    } catch (err) {
      // Surface the failure inline and keep the dialog open so the operator can
      // fix the input and retry — silently swallowing it made the button look dead.
      const detail = err instanceof ApiError ? err.message : t("createErrorUnknown");
      setError(t("createError", { detail }));
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
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("cancel")}
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
