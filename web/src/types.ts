export type Band = "Critical" | "High" | "Medium" | "Low" | "Insufficient data";

export interface Profile { id: string; description: string; currency: string; as_of: string }
export interface AIStatus { enabled: boolean; provider: string | null; model: string | null; disabled_reason: string | null; prompt_version: string }
export interface Config { profiles: Profile[]; decisions: string[]; bands: Band[]; samples: { profile: string; variant: string }[]; ai: AIStatus }

export interface ValidationIssue {
  table: string; record_key: string; field: string | null; issue: string;
  severity: "error" | "warning"; action: "quarantined" | "kept" | "repaired";
}
export interface Quality {
  tables: Record<string, number>; issue_count: number;
  severity: { error: number; warning: number };
  action: { quarantined: number; repaired: number; kept: number };
  quarantined: Record<string, number>; blocking: ValidationIssue[];
  has_signal_config: boolean; issues: ValidationIssue[];
}
export interface DatasetMeta {
  dataset_id: string; label: string; origin: string; profile_hint: string | null;
  files: string[]; created_at: string; quality?: Quality;
}
export interface RunMeta {
  run_id: string; created_at: string; profile: string; engine: string;
  dataset_id: string; dataset_label: string; customer_count: number;
}
export interface Factor { signal_id: string; name: string; points: number }
export interface WatchRow {
  customer_id: string; customer_name: string; customer_type: string; segment: string; portfolio: string;
  region: string; industry: string; main_product: string; products: string[]; total_outstanding: number | null;
  current_dpd: number | null; delinquency_bucket: string; score: number | null; band: Band; status: string;
  monitoring_status: string; confidence: number; signals_active: number; top_factors: Factor[]; summary: string;
  review_decision: string | null; reviewed_at: string | null;
  next_action: string | null; next_action_owner: string | null; next_action_due: string | null; action_count: number;
  active_signals: string[];
}
export interface Facets { [key: string]: string[] }
export interface WatchlistPage { total: number; page: number; page_size: number; rows: WatchRow[]; facets: Facets }

export interface Cluster {
  dimension: string; value: string; n_customers: number; n_elevated: number; lift: number; p_value: number;
  basis: string; basis_hits: number; group_rate: number; portfolio_rate: number; elevated_lift: number;
  top_signals: string[]; top_signal_names: string[]; customer_ids: string[];
  exposure: number; elevated_exposure: number; members: WatchRow[];
}
export interface Summary {
  run: RunMeta; as_of: string; customers: number; bands: Record<Band, number>;
  exposure_by_band: Record<Band, number>; total_exposure: number; exposure_at_risk: number; elevated: number;
  average_confidence: number; score_histogram: number[];
  thresholds: { threshold: number; customers: number; exposure: number }[];
  top_signals: { signal_id: string; name: string; pillar: string; customers: number }[];
  pillar_prevalence: Record<string, number>;
  reviews: { elevated: number; reviewed: number; decisions: Record<string, number> };
  priority: WatchRow[]; clusters: Cluster[]; quality: Quality;
  actions: { customers_with_actions: number; by_owner: Record<string, number>; by_action: { action_id: string; title: string; owner: string; customers: number }[] };
}

export interface Signal {
  signal_id: string; name: string; pillar: string; pillar_name: string; status: string;
  evaluated: boolean; applicable: boolean; reason_not_evaluated: string | null; value: number | null;
  trigger: number; saturation: number; strength: number; weight: number; points: number; evidence: string[];
}
export interface Review { review_id: number; alert_id: number; decision: string; reason: string; analyst: string; created_at: string; customer_id?: string; ai_note_id?: number | null }
export interface RecommendedAction {
  action_id: string; title: string; owner: string; priority: number; due_days: number; due_date: string;
  detail: string; reasons: string[]; cites: string[];
}
export interface CaseNote {
  summary: string; key_findings: { text: string; cites: string[] }[];
  recommended_actions: { action_id: string; reason: string; cites: string[] }[];
  questions_for_customer: string[]; data_gaps: string[]; suggested_decision: string;
  suggested_decision_reason: string; caveats: string[];
}
export interface CaseNoteRecord {
  note_id: number; alert_id: number; created_at: string; source: string; model: string | null; prompt_version: string;
  requested_by: string; note: CaseNote; error: string | null; cached?: boolean;
  verification: { status: "verified" | "check"; unknown_citations: string[]; dropped_actions: string[]; unverified_numbers: number[] };
}
export type Row = Record<string, string | number | null>;
export interface CustomerDetail {
  customer: Row; row: WatchRow | null; alert_id: number; reviews: Review[];
  result: {
    customer_id: string; as_of: string; rules_version: string; status: string; score: number | null; band: Band | null;
    monitoring_status: string; confidence: number; pillar_scores: Record<string, number>; modifiers: string[];
    summary: string; signals: Signal[];
  };
  facilities: Row[]; delinquency: Row[]; repayments: Row[]; transactions: Row[]; exposure: Row[]; sme: Row[];
  recommended_actions: RecommendedAction[];
  repayment_months: { month: string; worst_dpd: number | null; instalments: number; late: number; partial: number; unpaid: number; amount_due: number | null; amount_paid: number | null }[];
}

export interface AIRecord<T> {
  output_id: number; kind: string; run_id: string; subject: string; created_at: string; source: string;
  model: string | null; requested_by: string; output: T; verification: Record<string, unknown> & { status: string };
  error: string | null; cached?: boolean;
}
export interface AskResult {
  filters: Record<string, string | string[] | number | null>; explanation: string; unsupported: string[]; dropped: string[];
  source: string; model: string | null; error: string | null; total: number; rows: WatchRow[];
}
export interface ClusterBriefing {
  headline: string; pattern: string; shared_drivers: { text: string; cites: string[] }[]; segment_wide: boolean;
  segment_wide_reason: string; segment_actions: string[]; customers_to_prioritise: string[]; caveats: string[];
}
export interface RiskMemo {
  title: string; headline: string; key_points: { text: string }[]; changes_since_last: string[]; clusters: string[];
  actions_due: string[]; data_quality: string; recommendations: string[];
}
export interface EvidenceCheck {
  document_type: string; issuer: string; document_date: string;
  verdict: "supports" | "partially supports" | "does not support" | "unreadable" | "not assessed";
  repayment_ids: string[]; matched_details: string[]; concerns: string[]; summary: string;
  file_name: string; file_sha: string; media_type: string; requested_repayment_id: string | null; claim: string;
}
export interface EvidenceDecision {
  decision_id: number; alert_id: number; repayment_id: string; output_id: number | null; accepted: number;
  note: string; analyst: string; created_at: string;
}
export interface ColumnMap { source: string; target: string }
export interface FileMap { file: string; table: string; columns: ColumnMap[] }
export interface MappingProposal {
  files: FileMap[]; notes: string[]; dropped: string[]; missing_required: Record<string, string[]>;
  tables_not_supplied: string[]; targets: Record<string, string[]>; source: string; model: string | null; error: string | null;
}
