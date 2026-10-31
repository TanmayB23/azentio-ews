import type { Cluster, Config, CustomerDetail, DatasetMeta, MLPrediction, Review, RunMeta, Summary, WatchlistPage } from "./types";

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
  upload: (files: File[], label: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("label", label);
    return request<DatasetMeta>("/api/datasets/upload", { method: "POST", body: form });
  },
  quarantined: (id: string, table: string) => request<Record<string, unknown>[]>(`/api/datasets/${id}/quarantined/${table}`),
  runs: () => request<RunMeta[]>("/api/runs"),
  createRun: (dataset_id: string, profile: string) => request<RunMeta>("/api/runs", json({ dataset_id, profile })),
  summary: (run: string) => request<Summary>(`/api/runs/${run}/summary`),
  watchlist: (run: string, params: WatchParams) => request<WatchlistPage>(`/api/runs/${run}/watchlist${query(params)}`),
  watchlistCsvUrl: (run: string, params: WatchParams) => `/api/runs/${run}/watchlist.csv${query(params)}`,
  clusters: (run: string) => request<Cluster[]>(`/api/runs/${run}/clusters`),
  mlPrediction: (run: string, cid: string) => request<MLPrediction>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/ml`),
  customer: (run: string, cid: string) => request<CustomerDetail>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}`),
  alertUrl: (run: string, cid: string) => `/api/runs/${run}/customers/${encodeURIComponent(cid)}/alert.json`,
  addReview: (run: string, cid: string, body: { decision: string; reason: string; analyst: string }) =>
    request<Review>(`/api/runs/${run}/customers/${encodeURIComponent(cid)}/reviews`, json(body)),
  reviewLog: (run: string) => request<Review[]>(`/api/runs/${run}/reviews`),
};
