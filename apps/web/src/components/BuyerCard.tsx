"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { BuyerMatch } from "@/lib/types";
import { ScoreBreakdown, ScoreRing } from "./ScoreBreakdown";

const SOURCE_STYLES: Record<string, string> = {
  customs: "bg-brand-50 text-brand-700",
  comtrade: "bg-blue-50 text-blue-700",
  enrichment: "bg-violet-50 text-violet-700",
  maps: "bg-amber-50 text-amber-700",
  manual: "bg-gray-100 text-gray-600",
};

// Known provenance sources get a localized label; anything unexpected falls
// back to the raw value rather than showing a missing-key string.
const KNOWN_SOURCES = new Set(["customs", "comtrade", "enrichment", "maps", "manual"]);

export function BuyerCard({ match }: { match: BuyerMatch }) {
  const t = useTranslations("buyers");
  const [expanded, setExpanded] = useState(false);
  const { buyer, evidence, contacts, relevance_score, score_breakdown } = match;
  const verified = contacts.some((c) => c.verification_status === "valid");

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5">
      <div className="flex items-start gap-4">
        <ScoreRing score={relevance_score} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-gray-900">{buyer.name}</h3>
            <span className="text-sm text-gray-400">{buyer.country_iso2}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${SOURCE_STYLES[buyer.source] ?? SOURCE_STYLES.manual}`}
            >
              {t("source")}: {KNOWN_SOURCES.has(buyer.source) ? t(`source_${buyer.source}`) : buyer.source}
            </span>
            {contacts.length > 0 && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${
                  verified ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
                }`}
              >
                {verified ? t("verified") : t("unverified")}
              </span>
            )}
            {buyer.is_stale && (
              <span
                className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
                title={buyer.valid_until ?? undefined}
              >
                ⚠ {t("stale")}
              </span>
            )}
          </div>

          {evidence?.summary && (
            <p className="mt-1 text-sm text-gray-600">{evidence.summary}</p>
          )}
          {buyer.industry && (
            <p className="mt-0.5 text-xs text-gray-400">
              {buyer.industry}
              {buyer.employee_count ? ` · ${buyer.employee_count}` : ""}
            </p>
          )}

          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-2 text-xs font-medium text-brand-600 hover:underline"
          >
            {t("breakdown")}
          </button>
          {expanded && score_breakdown && <ScoreBreakdown breakdown={score_breakdown} />}

          {expanded && contacts.length > 0 && (
            <div className="mt-3 border-t border-gray-100 pt-2">
              <p className="text-xs font-medium text-gray-500">{t("contacts")}</p>
              <ul className="mt-1 space-y-1">
                {contacts.map((c) => (
                  <li key={c.id} className="text-xs text-gray-600">
                    {c.full_name ? `${c.full_name} · ` : ""}
                    <span dir="ltr">{c.email}</span>
                    {c.title ? ` · ${c.title}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
