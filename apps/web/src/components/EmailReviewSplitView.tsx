"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type { BuyerMatch, Email } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  approved: "bg-blue-50 text-blue-700",
  rejected: "bg-red-50 text-red-600",
  queued: "bg-amber-50 text-amber-700",
  sent: "bg-brand-50 text-brand-700",
  opened: "bg-brand-100 text-brand-700",
  replied: "bg-green-100 text-green-700",
  bounced: "bg-red-100 text-red-700",
  blocked_suppressed: "bg-red-50 text-red-600",
  cancelled: "bg-gray-100 text-gray-400",
};

export function EmailReviewSplitView({
  email,
  buyer,
  onChanged,
}: {
  email: Email;
  buyer?: BuyerMatch;
  onChanged: () => void;
}) {
  const t = useTranslations("campaign");
  const st = useTranslations("campaign.status");
  const bt = useTranslations("buyers");
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body_text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readOnly = email.status !== "draft";

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "error");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    await act(async () => {
      await api.put(`/emails/${email.id}`, { subject, body_text: body });
      setEditing(false);
    });
  }

  async function approve() {
    if (!confirm(t("approveConfirm"))) return;
    // Approve, then queue → dispatches the guarded send task on the backend.
    await act(async () => {
      await api.post(`/emails/${email.id}/approve`);
      await api.post(`/emails/${email.id}/queue`);
    });
  }

  return (
    <div className="rounded-xl bg-white shadow-sm ring-1 ring-black/5">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
        <span className="text-sm text-gray-500" dir="ltr">
          {buyer?.buyer.name ?? email.buyer_id.slice(0, 8)}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLES[email.status] ?? STATUS_STYLES.draft}`}
        >
          {st(email.status)}
        </span>
      </div>

      <div className="grid gap-0 md:grid-cols-2">
        {/* Buyer context */}
        <div className="border-b border-gray-100 p-4 md:border-b-0 md:border-e">
          <p className="text-xs font-medium text-gray-500">{t("buyerContext")}</p>
          {buyer?.evidence?.summary && (
            <p className="mt-2 text-sm text-gray-700">{buyer.evidence.summary}</p>
          )}
          {buyer && (
            <p className="mt-1 text-xs text-gray-400">
              {bt("relevanceScore")}: <span className="tabular font-bold">{buyer.relevance_score}</span>
              {buyer.buyer.industry ? ` · ${buyer.buyer.industry}` : ""}
            </p>
          )}
          {buyer && buyer.contacts.length > 0 && (
            <p className="mt-2 text-xs text-gray-500" dir="ltr">
              {buyer.contacts[0].email}
            </p>
          )}
        </div>

        {/* Editable draft */}
        <div className="p-4">
          <p className="text-xs font-medium text-gray-500">{t("emailDraft")}</p>
          {editing && !readOnly ? (
            <div className="mt-2 space-y-2">
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm text-start"
              />
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={10}
                className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm text-start"
                dir={["ar", "ur", "he", "fa"].includes(email.language) ? "rtl" : "ltr"}
              />
            </div>
          ) : (
            <div className="mt-2">
              <p className="text-sm font-medium text-gray-900">{email.subject}</p>
              <pre
                className="mt-2 whitespace-pre-wrap font-sans text-sm text-gray-700"
                dir={["ar", "ur", "he", "fa"].includes(email.language) ? "rtl" : "ltr"}
              >
                {email.body_text}
              </pre>
            </div>
          )}
        </div>
      </div>

      {error && <p className="px-4 pb-2 text-sm text-red-600">{error}</p>}

      {!readOnly && (
        <div className="flex flex-wrap justify-end gap-2 border-t border-gray-100 px-4 py-3">
          {editing ? (
            <button
              onClick={save}
              disabled={busy}
              className="rounded-lg bg-gray-800 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-900 disabled:opacity-60"
            >
              {t("save")}
            </button>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              {t("edit")}
            </button>
          )}
          <button
            onClick={() => act(() => api.post(`/emails/${email.id}/reject`, {}))}
            disabled={busy}
            className="rounded-lg border border-red-200 px-4 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
          >
            {t("reject")}
          </button>
          <button
            onClick={approve}
            disabled={busy}
            className="rounded-lg bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("approve")}
          </button>
        </div>
      )}
    </div>
  );
}
