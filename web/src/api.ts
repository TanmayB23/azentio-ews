import type {
  AIRecord, AskResult, CaseNoteRecord, Cluster, ClusterBriefing, Config, CustomerDetail, DatasetMeta, EvidenceCheck,
  EvidenceDecision, MappingProposal, Review, RiskMemo, RunMeta, Summary, WatchlistPage,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : message;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export type WatchParams = Record<string, string | string[] | number | undefined>;

export function query(params: WatchParams): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, v));
    else qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const api = {
  config: () => request<Config>("/api/config"),
  datasets: () => request<DatasetMeta[]>("/api/datasets"),
  dataset: (id: string) => request<DatasetMeta>(`/api/datasets/${id}`),
  loadSample: (profile: string, variant: string) => request<DatasetMeta>("/api/datasets/sample", json({ profile, variant })),
  upload: (files: File[], label: string, mapping?: { files: MappingProposal["files"]; notes: string[] }) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("label", label);
    if (mapping) form.append("column_mapping", JSON.stringify(mapping));
    return request<DatasetMeta>("/api/datasets/upload", { method: "POST", body: form });
  },
  proposeMapping: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<MappingProposal>("/api/datasets/propose-mapping", { method: "POST", body: form });
  },
  quarantined: (id: string, table: string) => request<Record<string, unknown>[]>(`/api/datasets/${id}/quarantined/${table}`),
  runs: () => request<RunMeta[]>("/api/runs"),
  createRun: (dataset_id: string, profile: string) => request<RunMeta>("/api/runs", json({ dataset_id, profile })),
  summary: (run: string) => request<Summary>(`/api/runs/${run}/summary`),
  watchlist: (run: string, params: WatchParams) => request<WatchlistPage>(`/api/runs/${run}/watchlist${query(params)}`),
  watchlistCsvUrl: (run: string, params: WatchParams) => `/api/runs/${run}/watchlist.csv${query(params)}`,
  clusters: (run: string) => request<Cluster[]>(`/api/runs/${run}/clusters`),
  customer: (run: string, cid: string) => request<CustomerDetail>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}`),
  alertUrl: (run: string, cid: string) => `/api/runs/${run}/customers/${encodeURIComponent(cid)}/alert.json`,
  addReview: (run: string, cid: string, body: { decision: string; reason: string; analyst: string; ai_note_id?: number | null }) =>
    request<Review>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/reviews`, json(body)),
  reviewLog: (run: string) => request<Review[]>(`/api/runs/${run}/reviews`),
  ask: (run: string, question: string, analyst: string) => request<AskResult>(`/api/runs/${run}/ask`, json({ question, analyst })),
  clusterBriefing: (run: string, body: { dimension: string; value: string; analyst: string; regenerate: boolean }) =>
    request<AIRecord<ClusterBriefing>>(`/api/runs/${run}/clusters/briefing`, json(body)),
  clusterBriefings: (run: string, dimension: string, value: string) =>
    request<AIRecord<ClusterBriefing>[]>(`/api/runs/${run}/clusters/briefings${query({ dimension, value })}`),
  memo: (run: string, body: { analyst: string; regenerate: boolean }) =>
    request<AIRecord<RiskMemo> & { compared_with: RunMeta | null }>(`/api/runs/${run}/memo`, json(body)),
  memos: (run: string) => request<AIRecord<RiskMemo>[]>(`/api/runs/${run}/memo`),
  memoUrl: (run: string, id: number) => `/api/runs/${run}/memo/${id}.md`,
  evidenceChecks: (run: string, cid: string) =>
    request<AIRecord<EvidenceCheck>[]>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/evidence-checks`),
  checkEvidence: (run: string, cid: string, file: File, repaymentId: string, claim: string, analyst: string) => {
    const form = new FormData();
    form.append("file", file); form.append("repayment_id", repaymentId); form.append("claim", claim); form.append("analyst", analyst);
    return request<AIRecord<EvidenceCheck>>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/evidence-checks`, { method: "POST", body: form });
  },
  evidenceDecisions: (run: string, cid: string) =>
    request<EvidenceDecision[]>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/evidence-decisions`),
  decideEvidence: (run: string, cid: string, body: { repayment_id: string; accepted: boolean; note: string; analyst: string; output_id: number | null }) =>
    request<EvidenceDecision>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/evidence-decisions`, json(body)),
  caseNotes: (run: string, cid: string) => request<CaseNoteRecord[]>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/case-notes`),
  draftCaseNote: (run: string, cid: string, body: { analyst: string; regenerate: boolean }) =>
    request<CaseNoteRecord>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/case-notes`, json(body)),
};
