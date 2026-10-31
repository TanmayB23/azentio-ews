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


export interface MLFactor {
  signal_id: string; name: string; value: number | null; evaluated: boolean; applicable: boolean;
  reason: string | null; contribution: number; direction: "increases" | "decreases" | "neutral";
}
export interface MLModelMetadata {
  model_id: string; trained_at: string; algorithm: string; training_data_kind: string;
  feature_ids: string[]; feature_signatures: Record<string, string>; split: string;
  calibration: { method: string; slope: number; intercept: number };
  splits: Record<string, { rows: number; customers: number; positive_rows: number; origin_start: string; origin_end: string; last_label_date: string }>;
  evaluation: { roc_auc: number; average_precision: number; brier_score: number; log_loss: number;
    event_rate: number; constant_baseline_brier: number; calibration_bins: { count: number; mean_prediction: number; observed_rate: number }[] };
  limitations: string[];
}
export interface MLPrediction {
  status: "predicted" | "insufficient_data" | "already_delinquent" | "model_unavailable";
  probability: number | null; reason: string | null; as_of: string; horizon_end: string;
  threshold_dpd: number; horizon_months: number; factors: MLFactor[]; model: MLModelMetadata | null;
  disclaimer: string; prediction_id?: string; model_id?: string; created_at?: string;
  base_probability?: number; base_log_odds?: number; log_odds?: number; explanation_method?: string;
}
