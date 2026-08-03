"use client";

import { useTranslations } from "next-intl";
import type { ScoreBreakdown as Breakdown } from "@/lib/types";

export function ScoreBreakdown({ breakdown }: { breakdown: Breakdown }) {
  const t = useTranslations("buyers.factors");

  return (
    <div className="mt-3 space-y-2">
      {Object.entries(breakdown.factors).map(([key, factor]) => {
        const pct = factor.max ? (factor.points / factor.max) * 100 : 0;
        return (
          <div key={key}>
            <div className="flex items-center justify-between text-xs text-gray-600">
              <span>{t.has(key) ? t(key) : key}</span>
              <span className="tabular">
                {factor.points}/{factor.max}
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
              <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-0.5 text-xs text-gray-400">{factor.detail}</p>
          </div>
        );
      })}
    </div>
  );
}

export function ScoreRing({ score }: { score: number }) {
  const color =
    score >= 70 ? "text-brand-600" : score >= 40 ? "text-amber-500" : "text-gray-400";
  return (
    <div className={`flex h-14 w-14 items-center justify-center rounded-full ring-4 ring-current ${color}`}>
      <span className="tabular text-lg font-bold text-gray-800">{score}</span>
    </div>
  );
}
