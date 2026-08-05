"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { Link } from "@/i18n/routing";
import { api, ApiError, TOKEN_COOKIE } from "@/lib/api";
import { decodeRole, isStaffRole } from "@/lib/auth";

interface TokenResponse {
  access_token: string;
}

export default function LoginPage() {
  const t = useTranslations("auth");
  const router = useRouter();
  const [email, setEmail] = useState("factory1@demo.silk");
  const [password, setPassword] = useState("Demo1234!");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.post<TokenResponse>("/auth/login", { email, password });
      // Secure over HTTPS (prod); omitted on http://localhost so dev login still works.
      const secure = window.location.protocol === "https:" ? "; Secure" : "";
      document.cookie = `${TOKEN_COOKIE}=${res.access_token}; path=/; max-age=43200; samesite=lax${secure}`;
      // Staff land in the concierge console; factory users in their dashboard.
      router.push(isStaffRole(decodeRole(res.access_token)) ? "/admin" : "/dashboard");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        // 401 means the credentials were rejected; any other status is a
        // server-side failure and must not read as "wrong password".
        setError(err.status === 401 ? t("loginError") : t("serverError"));
      } else {
        // fetch rejects (TypeError) when the backend is unreachable.
        setError(t("connectionError"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-sm ring-1 ring-black/5">
        <h1 className="text-2xl font-bold text-brand-700">{t("welcome")}</h1>
        <p className="mt-1 text-sm text-gray-500">{t("login")}</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Field
            label={t("email")}
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
          />
          <Field
            label={t("password")}
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("loginCta")}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          {t("noAccount")}{" "}
          <Link href="/register" className="font-medium text-brand-600 hover:underline">
            {t("register")}
          </Link>
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
  autoComplete,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        required
      />
    </label>
  );
}
