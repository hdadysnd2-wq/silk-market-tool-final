"use client";

import { useTranslations } from "next-intl";

// Cross-tenant campaign oversight is finished under B5; this keeps the nav
// destination live so the shell is navigable now.
export default function AdminCampaignsPage() {
  const t = useTranslations("admin");
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("campaigns")}</h1>
      <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
        {t("comingSoon")}
      </p>
    </div>
  );
}
