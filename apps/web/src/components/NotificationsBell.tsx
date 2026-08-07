"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  read_at: string | null;
  created_at: string;
}

/**
 * Surfaces the operator alerts the backend already writes (mailbox reauth, new
 * replies, send interrupted, campaigns paused, stuck sends). Before this, those
 * notifications had no UI at all (audit) — a broken mailbox was invisible unless
 * the user happened to open Settings. Polls, shows an unread count, marks read.
 */
export function NotificationsBell() {
  const t = useTranslations("notifications");
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<Notification[]>("/notifications", 60000);
  const items = data ?? [];
  const unread = items.filter((n) => !n.read_at).length;

  async function markRead(id: string) {
    try {
      await api.post(`/notifications/${id}/read`, {});
      reload();
    } catch {
      // Non-fatal: the badge will re-sync on the next poll.
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-lg px-2 py-1 text-sm text-gray-500 hover:text-gray-800"
        aria-label={t("title")}
      >
        <span aria-hidden>🔔</span>
        {unread > 0 && (
          <span className="absolute -end-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-medium text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute end-0 z-10 mt-2 w-80 rounded-xl bg-white p-2 shadow-lg ring-1 ring-black/10">
          <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
            {t("title")}
          </p>
          {items.length === 0 ? (
            <p className="px-2 py-4 text-center text-sm text-gray-400">{t("empty")}</p>
          ) : (
            <ul className="max-h-96 space-y-1 overflow-y-auto">
              {items.slice(0, 20).map((n) => (
                <li
                  key={n.id}
                  className={`rounded-lg p-2 text-sm ${n.read_at ? "opacity-60" : "bg-brand-50"}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-medium text-gray-900">{n.title}</p>
                      {n.body && <p className="mt-0.5 text-xs text-gray-600">{n.body}</p>}
                    </div>
                    {!n.read_at && (
                      <button
                        type="button"
                        onClick={() => markRead(n.id)}
                        className="shrink-0 text-xs font-medium text-brand-600 hover:text-brand-700"
                      >
                        {t("markRead")}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
