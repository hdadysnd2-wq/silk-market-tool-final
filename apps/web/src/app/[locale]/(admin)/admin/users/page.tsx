"use client";

import { useTranslations } from "next-intl";

// Full user-management UI arrives with B4 (create/deactivate/reset-password on
// top of the B3 API). This shell page keeps the nav destination live.
export default function AdminUsersPage() {
  const t = useTranslations("admin");
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{t("users")}</h1>
      <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
        {t("comingSoon")}
      </p>
    </div>
  );
}
