"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { Factory } from "@/lib/types";

export default function OnboardingPage() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const { data: factory } = useApi<Factory>("/factory");

  if (!factory) return <p className="text-gray-400">…</p>;

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const payload = Object.fromEntries(form.entries());
    await api.put("/factory", { ...payload, onboarding_completed: true });
    // Next onboarding step: connect a sending mailbox (a hard prerequisite for
    // creating campaigns).
    router.push("/onboarding/email");
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900">{t("title")}</h1>
      <form onSubmit={submit} className="mt-6 space-y-4 rounded-xl bg-white p-6 shadow-sm ring-1 ring-black/5">
        <p className="text-sm font-medium text-gray-500">{t("step1")}</p>
        <div className="grid grid-cols-2 gap-3">
          <Input name="sector" label={t("sector")} defaultValue={factory.sector ?? ""} />
          <Input name="city" label={t("city")} defaultValue={factory.city ?? ""} />
        </div>
        <Input name="website" label={t("website")} defaultValue={factory.website ?? ""} />

        <p className="pt-2 text-sm font-medium text-gray-500">{t("step2")}</p>
        <div className="grid grid-cols-2 gap-3">
          <Input name="contact_person" label={t("contactPerson")} defaultValue={factory.contact_person ?? ""} />
          <Input name="contact_email" label={t("contactEmail")} defaultValue={factory.contact_email ?? ""} />
        </div>
        <Input name="contact_phone" label={t("contactPhone")} defaultValue={factory.contact_phone ?? ""} />
        <Input name="postal_address" label={t("postalAddress")} defaultValue={factory.postal_address ?? ""} />

        <p className="pt-2 text-sm font-medium text-gray-500">{t("step3")}</p>
        <Input name="sending_domain" label={t("step3")} defaultValue={factory.sending_domain ?? ""} />

        <button
          type="submit"
          className="mt-2 w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700"
        >
          {t("complete")}
        </button>
      </form>
    </div>
  );
}

function Input({ name, label, defaultValue }: { name: string; label: string; defaultValue?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        name={name}
        defaultValue={defaultValue}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
      />
    </label>
  );
}
