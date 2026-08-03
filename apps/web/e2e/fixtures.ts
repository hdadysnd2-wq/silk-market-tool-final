import type { BuyerMatch, SenderAccount } from "@/lib/types";

/**
 * A JWT-shaped token whose payload base64-decodes to a factory_user role. The
 * (app) layout only reads the role (no signature check), and every API call is
 * mocked, so this is enough to pass the auth gate in e2e.
 */
export function fakeToken(role = "factory_user"): string {
  const payload = Buffer.from(JSON.stringify({ sub: "u1", role })).toString("base64");
  return `header.${payload}.sig`;
}

export const VERIFIED_ACCOUNT: SenderAccount = {
  id: "acc-1",
  email: "owner@factory.example",
  provider_type: "gmail",
  display_name: "Owner",
  verification_status: "verified",
  reauth_reason: null,
  scopes: "mailbox.send mailbox.read",
  daily_send_limit: 50,
  daily_sent_count: 3,
  warmup_stage: 1,
  verified_at: "2026-01-01T00:00:00Z",
  last_polled_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

export const BUYER_MATCH: BuyerMatch = {
  buyer: {
    id: "buyer-1",
    name: "Acme Importers",
    country_iso2: "IN",
    city: "Mumbai",
    domain: "acme.example.in",
    website: null,
    industry: "Packaging",
    employee_count: 120,
    source: "customs",
    source_confidence: 0.85,
    legal_review_required: false,
  },
  market_iso2: "IN",
  relevance_score: 82,
  score_breakdown: null,
  evidence: { summary: "Imported 42 shipments in the last 12 months" },
  contacts: [],
};

// A second buyer in a different market, so the unfiltered buyers view (the
// "discover across the top markets" landing) spans more than one market.
export const BUYER_MATCH_NL: BuyerMatch = {
  buyer: {
    id: "buyer-2",
    name: "Rotterdam Trading BV",
    country_iso2: "NL",
    city: "Rotterdam",
    domain: "rtx.example.nl",
    website: null,
    industry: "Wholesale",
    employee_count: 60,
    source: "comtrade",
    source_confidence: 0.8,
    legal_review_required: false,
  },
  market_iso2: "NL",
  relevance_score: 74,
  score_breakdown: null,
  evidence: { summary: "Imported 18 shipments in the last 12 months" },
  contacts: [],
};
