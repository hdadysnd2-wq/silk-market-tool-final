"use client";

import { useTranslations } from "next-intl";

/**
 * A real error state for data-fetch failures — replaces the "render the empty
 * state when data is null" pattern the audit flagged (a 500 used to look like
 * "you have no campaigns/replies"). Shows a message and an optional retry.
 */
export function ErrorNotice({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const t = useTranslations("common");
  return (
    <div
      role="alert"
      className="mt-6 rounded-xl bg-red-50 p-6 text-center ring-1 ring-red-200"
    >
      <p className="font-medium text-red-800">{t("error")}</p>
      <p className="mt-1 text-sm text-red-600">{message || t("loadError")}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          {t("retry")}
        </button>
      ) : null}
    </div>
  );
}
