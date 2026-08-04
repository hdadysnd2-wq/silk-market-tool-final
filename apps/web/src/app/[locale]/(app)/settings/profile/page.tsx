"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Factory, User } from "@/lib/types";

export default function ProfilePage() {
  const t = useTranslations("profile");
  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <FactorySection />
      <AccountSection />
      <PasswordSection />
    </div>
  );
}

// -- factory identity + read-only sending domain ---------------------------

function FactorySection() {
  const t = useTranslations("profile");
  const { data: factory, reload } = useApi<Factory>("/factory");
  const [nameAr, setNameAr] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [status, setStatus] = useState<Status>(null);

  useEffect(() => {
    if (factory) {
      setNameAr(factory.name_ar ?? "");
      setNameEn(factory.name_en ?? "");
    }
  }, [factory]);

  if (!factory) return <p className="text-gray-400">…</p>;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await api.put("/factory", { name_ar: nameAr, name_en: nameEn });
      await reload();
      setStatus({ ok: true, msg: t("saved") });
    } catch (err) {
      setStatus({ ok: false, msg: errMsg(err, t("saveError")) });
    }
  }

  const dnsRows: { label: string; ok: boolean }[] = [
    { label: t("spf"), ok: factory.spf_ok },
    { label: t("dkim"), ok: factory.dkim_ok },
    { label: t("dmarc"), ok: factory.dmarc_ok },
  ];

  return (
    <Card title={t("factoryTitle")}>
      <form onSubmit={save} className="space-y-4">
        <Field label={t("factoryNameAr")} value={nameAr} onChange={setNameAr} dir="rtl" required />
        <Field label={t("factoryNameEn")} value={nameEn} onChange={setNameEn} dir="ltr" required />

        <div>
          <p className="mb-1 text-sm font-medium text-gray-700">{t("sendingDomain")}</p>
          <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-900" dir="ltr">
            {factory.sending_domain ?? "—"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {dnsRows.map((row) => (
              <span
                key={row.label}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  row.ok ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                }`}
              >
                {row.label}: {row.ok ? t("verified") : t("notVerified")}
              </span>
            ))}
          </div>
        </div>

        <StatusLine status={status} />
        <SubmitButton>{t("saveFactory")}</SubmitButton>
      </form>
    </Card>
  );
}

// -- account name + UI locale ----------------------------------------------

function AccountSection() {
  const t = useTranslations("profile");
  const { data: me, reload } = useApi<User>("/auth/me");
  const [fullName, setFullName] = useState("");
  const [locale, setLocale] = useState("ar");
  const [status, setStatus] = useState<Status>(null);

  useEffect(() => {
    if (me) {
      setFullName(me.full_name ?? "");
      setLocale(me.locale ?? "ar");
    }
  }, [me]);

  if (!me) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await api.put("/auth/me", { full_name: fullName, locale });
      await reload();
      setStatus({ ok: true, msg: t("saved") });
    } catch (err) {
      setStatus({ ok: false, msg: errMsg(err, t("saveError")) });
    }
  }

  return (
    <Card title={t("accountTitle")}>
      <form onSubmit={save} className="space-y-4">
        <div>
          <p className="mb-1 text-sm font-medium text-gray-700">{t("email")}</p>
          <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-900" dir="ltr">
            {me.email}
          </p>
        </div>
        <Field label={t("fullName")} value={fullName} onChange={setFullName} />
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("locale")}</span>
          <select
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          >
            <option value="ar">{t("localeAr")}</option>
            <option value="en">{t("localeEn")}</option>
          </select>
        </label>
        <StatusLine status={status} />
        <SubmitButton>{t("saveAccount")}</SubmitButton>
      </form>
    </Card>
  );
}

// -- change password -------------------------------------------------------

function PasswordSection() {
  const t = useTranslations("profile");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<Status>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    if (next !== confirm) {
      setStatus({ ok: false, msg: t("passwordMismatch") });
      return;
    }
    if (next.length < 8) {
      setStatus({ ok: false, msg: t("passwordTooShort") });
      return;
    }
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setStatus({ ok: true, msg: t("passwordChanged") });
    } catch (err) {
      setStatus({ ok: false, msg: errMsg(err, t("passwordError")) });
    }
  }

  return (
    <Card title={t("passwordTitle")}>
      <form onSubmit={save} className="space-y-4">
        <Field
          label={t("currentPassword")}
          value={current}
          onChange={setCurrent}
          type="password"
          required
        />
        <Field label={t("newPassword")} value={next} onChange={setNext} type="password" required />
        <Field
          label={t("confirmPassword")}
          value={confirm}
          onChange={setConfirm}
          type="password"
          required
        />
        <StatusLine status={status} />
        <SubmitButton>{t("changePassword")}</SubmitButton>
      </form>
    </Card>
  );
}

// -- shared bits -----------------------------------------------------------

type Status = { ok: boolean; msg: string } | null;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-black/5">
      <h2 className="mb-4 text-lg font-semibold text-gray-900">{title}</h2>
      {children}
    </section>
  );
}

function StatusLine({ status }: { status: Status }) {
  if (!status) return null;
  return (
    <p className={`text-sm ${status.ok ? "text-green-700" : "text-red-600"}`} role="status">
      {status.msg}
    </p>
  );
}

function SubmitButton({ children }: { children: React.ReactNode }) {
  return (
    <button
      type="submit"
      className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700"
    >
      {children}
    </button>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  dir,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  dir?: "rtl" | "ltr";
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        type={type}
        value={value}
        dir={dir}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        required={required}
      />
    </label>
  );
}
