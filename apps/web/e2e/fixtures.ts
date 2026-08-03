import type {
  BuyerMatch,
  Campaign,
  Email,
  EmailStatus,
  Factory,
  ProductReport,
  SenderAccount,
} from "@/lib/types";

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

export const CAMPAIGN: Campaign = {
  id: "camp-1",
  factory_id: "fac-1",
  product_id: "prod-1",
  sender_account_id: "acc-1",
  market_iso2: "IN",
  name: "Outreach → IN",
  status: "draft",
  paused_reason: null,
  total_emails: 4,
  sent_count: 1,
  opened_count: 0,
  replied_count: 0,
  bounced_count: 0,
  complained_count: 0,
  reported_meetings: 0,
  reported_rfqs: 0,
  created_at: "2026-01-01T00:00:00Z",
  market_is_eu: false,
  lia_recorded: false,
};

function email(id: string, status: EmailStatus): Email {
  const cleared = status === "approved" || status === "queued" || status === "sent";
  return {
    id,
    campaign_id: "camp-1",
    contact_id: `contact-${id}`,
    buyer_id: "buyer-1",
    status,
    subject: `Subject ${id}`,
    body_text: `Body ${id}`,
    body_html: null,
    language: "en",
    is_followup: false,
    approved_at: cleared ? "2026-01-02T00:00:00Z" : null,
    sent_at: status === "sent" ? "2026-01-02T00:00:00Z" : null,
    opened_at: null,
    replied_at: null,
    blocked_reason: null,
  };
}

// Two drafts awaiting review, one approved, one already sent → the approval
// summary should read 2 pending · 1 approved · 1 sent.
export const EMAILS: Email[] = [
  email("e1", "draft"),
  email("e2", "draft"),
  email("e3", "approved"),
  email("e4", "sent"),
];

// A factory whose DNS is unverified and whose warm-up hasn't started, so the
// deliverability screen shows every action button (verify SPF/DKIM/DMARC,
// "Start warm-up") in its actionable state.
export const FACTORY: Factory = {
  id: "fac-1",
  name_ar: "مصنع التمور",
  name_en: "Dates Factory",
  description_ar: null,
  description_en: null,
  sector: "Food & Agriculture",
  city: "Riyadh",
  website: null,
  contact_person: null,
  contact_email: null,
  contact_phone: null,
  postal_address: null,
  sending_domain: "mail.factory.example",
  spf_ok: false,
  dkim_ok: false,
  dmarc_ok: false,
  warmup_day: 0,
  daily_send_count: 0,
  sends_paused: false,
  onboarding_completed: true,
};

// A minimal product report — enough for the report screen to render its header
// and summary tiles and offer the "Download HTML" action. No markets so the
// long market list stays out of the render.
export const PRODUCT_REPORT: ProductReport = {
  generated_at: "2026-01-01T00:00:00Z",
  locale: "en",
  factory: {
    name_en: "Dates Factory",
    name_ar: "مصنع التمور",
    sector: "Food & Agriculture",
    city: "Riyadh",
    website: null,
    contact_person: null,
    contact_email: null,
    contact_phone: null,
  },
  product: {
    id: "prod-1",
    name_en: "Premium Dates",
    name_ar: "تمور فاخرة",
    description_en: "Saudi Medjool dates",
    description_ar: null,
    image_url: null,
    price_min: 10,
    price_max: 20,
    currency: "USD",
    hs_code: "080410",
    hs_description_en: "Dates, fresh or dried",
    hs_description_ar: "تمور",
    hs_confirmed_by_user: true,
    classification_status: "classified",
    hs_confidence: 0.92,
  },
  summary: {
    markets_analyzed: 1,
    total_buyers: 1,
    total_contacts: 0,
    verified_contacts: 0,
    total_import_usd: 5_000_000,
    top_market_iso2: "IN",
  },
  funnel: null,
  markets: [],
};
