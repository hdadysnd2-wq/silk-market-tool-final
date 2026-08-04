// Hand-maintained mirrors of the backend Pydantic schemas. Both sides are
// written together in this monorepo, so codegen isn't worth the toolchain.

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "factory_user" | "admin" | "analyst";
  factory_id: string | null;
  locale: string;
}

export interface Factory {
  id: string;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  sector: string | null;
  city: string | null;
  website: string | null;
  contact_person: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  postal_address: string | null;
  sending_domain: string | null;
  spf_ok: boolean;
  dkim_ok: boolean;
  dmarc_ok: boolean;
  warmup_day: number;
  daily_send_count: number;
  sends_paused: boolean;
  onboarding_completed: boolean;
}

export interface HSCandidate {
  code: string;
  confidence: number;
  rationale: string | null;
  description_en: string | null;
  description_ar: string | null;
  in_catalogue: boolean;
}

export interface Product {
  id: string;
  factory_id: string;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string;
  hs_code: string | null;
  hs_candidates: HSCandidate[] | null;
  hs_confirmed_by_user: boolean;
  classification_status: string;
  created_at: string;
}

export interface Market {
  iso2: string;
  name_en: string;
  name_ar: string;
  region: string | null;
  primary_language: string;
  is_gcc: boolean;
  is_eu: boolean;
  is_us: boolean;
}

export interface CountryRanking {
  rank: number;
  importer_iso3: string;
  //: alpha-2 for the competitor/buyer deep-dive; null for an unmapped market.
  market_iso2: string | null;
  year: number | null;
  import_usd: number | null;
  yoy_growth: number | null;
  cagr_3y: number | null;
  screen_score: number;
  is_transit_hub: boolean;
  is_mirror: boolean;
  tags: string[] | null;
  stage: number;
}

export interface Analysis {
  id: string;
  product_id: string | null;
  product_name: string;
  status: string;
  deepen: boolean;
  created_at: string;
  rankings: CountryRanking[];
}

export interface BriefFigure {
  label: string;
  //: null = a declared gap (I1), never a fabricated number.
  value: string | null;
  //: The provenance line shown under the figure — never omitted (decision #7).
  source: string;
  year: number | null;
}

export interface FunnelBrief {
  analysis_id: string;
  hs_code: string | null;
  decision: string;
  decisive_numbers: BriefFigure[];
  competitive_position: string[];
  //: "Limits of this report" — the declared gaps, never compressed away.
  limits: string[];
}

export interface ScoreFactor {
  points: number;
  max: number;
  detail: string;
}

export interface ScoreBreakdown {
  total: number;
  factors: Record<string, ScoreFactor>;
}

export interface Contact {
  id: string;
  email: string;
  full_name: string | null;
  title: string | null;
  language: string;
  verification_status: "unverified" | "valid" | "risky" | "invalid";
}

export interface Buyer {
  id: string;
  name: string;
  country_iso2: string;
  city: string | null;
  domain: string | null;
  website: string | null;
  industry: string | null;
  employee_count: number | null;
  source: "customs" | "comtrade" | "enrichment" | "maps" | "manual";
  source_confidence: number;
  legal_review_required: boolean;
  // Lead validity (rule 6 / I8): 90-day window derived from when the record was
  // last refreshed. A stale lead must be shown with an explicit warning.
  freshness_at: string | null;
  valid_until: string | null;
  is_stale: boolean;
}

export interface BuyerMatch {
  buyer: Buyer;
  market_iso2: string;
  relevance_score: number;
  score_breakdown: ScoreBreakdown | null;
  evidence: { summary?: string; shipment_count?: number } | null;
  contacts: Contact[];
}

export interface CompetitorSnapshot {
  hs_code: string;
  market_iso2: string;
  total_import_usd: number | null;
  trend_pct: number | null;
  top_exporters:
    | { exporter_iso2: string; exporter_name: string; value_usd: number; share_pct: number }[]
    | null;
  yearly_values: { year: number; value_usd: number }[] | null;
  source: string;
}

export type EmailStatus =
  | "draft"
  | "approved"
  | "rejected"
  | "queued"
  | "sent"
  | "opened"
  | "replied"
  | "bounced"
  | "complained"
  | "blocked_suppressed"
  | "cancelled";

export interface SenderAccount {
  id: string;
  email: string;
  provider_type: "gmail" | "microsoft" | "mock";
  display_name: string | null;
  verification_status: "pending" | "verified" | "needs_reauth" | "disabled";
  reauth_reason: string | null;
  scopes: string | null;
  daily_send_limit: number;
  daily_sent_count: number;
  warmup_stage: number;
  verified_at: string | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface Campaign {
  id: string;
  factory_id: string;
  product_id: string;
  sender_account_id: string | null;
  market_iso2: string;
  name: string;
  status: string;
  paused_reason: string | null;
  total_emails: number;
  sent_count: number;
  opened_count: number;
  replied_count: number;
  bounced_count: number;
  complained_count: number;
  reported_meetings: number;
  reported_rfqs: number;
  created_at: string;
  // EU markets require a Legitimate Interest Assessment before any send (I8).
  market_is_eu: boolean;
  lia_recorded: boolean;
}

export interface Email {
  id: string;
  campaign_id: string;
  contact_id: string;
  buyer_id: string;
  status: EmailStatus;
  subject: string;
  body_text: string;
  body_html: string | null;
  language: string;
  is_followup: boolean;
  approved_at: string | null;
  sent_at: string | null;
  opened_at: string | null;
  replied_at: string | null;
  blocked_reason: string | null;
}

export interface ReportSnapshot {
  total_import_usd: number | null;
  trend_pct: number | null;
  top_exporters: {
    exporter_iso2: string | null;
    exporter_name: string | null;
    value_usd: number | null;
    share_pct: number | null;
  }[];
  yearly_values: { year: number; value_usd: number | null }[];
  source: string;
}

export interface ReportBuyer {
  name: string;
  city: string | null;
  website: string | null;
  industry: string | null;
  employee_count: number | null;
  source: string;
  relevance_score: number;
  evidence_summary: string | null;
  legal_review_required: boolean;
  contacts: {
    full_name: string | null;
    title: string | null;
    email: string;
    verification_status: string;
  }[];
}

export interface ReportMarket {
  iso2: string;
  name_en: string;
  name_ar: string;
  is_gcc: boolean;
  is_eu: boolean;
  is_us: boolean;
  buyer_count: number;
  contact_count: number;
  snapshot: ReportSnapshot | null;
  top_buyers: ReportBuyer[];
}

export interface ReportFunnelMarket {
  rank: number;
  importer_iso3: string;
  market_iso2: string | null;
  year: number | null;
  import_usd: number | null;
  is_transit_hub: boolean;
  is_mirror: boolean;
  tags: string[] | null;
}

export interface ReportFunnel {
  hs_code: string | null;
  shortlisted_count: number;
  top_markets: ReportFunnelMarket[];
}

export interface ProductReport {
  generated_at: string;
  locale: string;
  factory: {
    name_en: string;
    name_ar: string;
    sector: string | null;
    city: string | null;
    website: string | null;
    contact_person: string | null;
    contact_email: string | null;
    contact_phone: string | null;
  };
  product: {
    id: string;
    name_en: string;
    name_ar: string;
    description_en: string | null;
    description_ar: string | null;
    image_url: string | null;
    price_min: number | null;
    price_max: number | null;
    currency: string;
    hs_code: string | null;
    hs_description_en: string | null;
    hs_description_ar: string | null;
    hs_confirmed_by_user: boolean;
    classification_status: string;
    hs_confidence: number | null;
  };
  summary: {
    markets_analyzed: number;
    total_buyers: number;
    total_contacts: number;
    verified_contacts: number;
    total_import_usd: number | null;
    top_market_iso2: string | null;
  };
  funnel: ReportFunnel | null;
  markets: ReportMarket[];
}

export interface DashboardStats {
  campaigns: number;
  total_sent: number;
  total_opened: number;
  total_replied: number;
  total_bounced: number;
  open_rate: number;
  reply_rate: number;
  bounce_rate: number;
  pending_approvals: number;
}
