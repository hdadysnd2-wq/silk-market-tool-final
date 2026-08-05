"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter, Link } from "@/i18n/routing";

export default function RegisterPage() {
  const t = useTranslations("auth");
  const router = useRouter();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    factory_name_ar: "",
    factory_name_en: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function set(key: keyof typeof form) {
    return (v: string) => setForm((f) => ({ ...f, [key]: v }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Server-side register + auto-login sets the httpOnly cookie; client never
      // holds the token.
      const res = await fetch("/api/session/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.detail ?? t("loginError"));
        return;
      }
      router.push("/onboarding");
      router.refresh();
    } catch {
      setError(t("connectionError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-4 py-8">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-sm ring-1 ring-black/5">
        <h1 className="text-2xl font-bold text-brand-700">{t("register")}</h1>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Field label={t("factoryNameAr")} value={form.factory_name_ar} onChange={set("factory_name_ar")} />
          <Field label={t("factoryNameEn")} value={form.factory_name_en} onChange={set("factory_name_en")} />
          <Field label={t("fullName")} value={form.full_name} onChange={set("full_name")} />
          <Field label={t("email")} type="email" value={form.email} onChange={set("email")} />
          <Field label={t("password")} type="password" value={form.password} onChange={set("password")} />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("registerCta")}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-gray-500">
          {t("haveAccount")}{" "}
          <Link href="/login" className="font-medium text-brand-600 hover:underline">
            {t("login")}
          </Link>
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        required
      />
    </label>
  );
}
