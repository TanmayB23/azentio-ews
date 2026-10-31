import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Search, X } from "lucide-react";
import { api } from "../api";
import { BandPill, Card, Empty, ErrorNote, MultiFilter, ReviewPill, ScoreBar, Skeleton, Spinner } from "../components/ui";
import { initials, money, num, pct, profileCurrency } from "../format";
import { useWorkspace } from "../state";
import { NoAssessment } from "./Overview";

const FILTERS: { key: string; label: string }[] = [
  { key: "band", label: "Risk band" },
  { key: "main_product", label: "Product" },
  { key: "segment", label: "Segment" },
  { key: "delinquency_bucket", label: "Delinquency" },
  { key: "portfolio", label: "Portfolio" },
  { key: "customer_type", label: "Customer type" },
  { key: "region", label: "Region" },
];
const PAGE_SIZE = 25;

export function Watchlist() {
  const { run } = useWorkspace();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const page = Number(params.get("page") ?? 1);
  const sort = params.get("sort") ?? "score";
  const order = params.get("order") ?? "desc";

  useEffect(() => { setSearch(params.get("q") ?? ""); }, [params]);

  const filters: Record<string, string[]> = Object.fromEntries(FILTERS.map((f) => [f.key, params.getAll(f.key)]));
  const review = params.get("review") ?? "";
  const query = { q: params.get("q") ?? "", ...filters, review, sort, order, page, page_size: PAGE_SIZE };
  const q = useQuery({
    queryKey: ["watchlist", run?.run_id, query], queryFn: () => api.watchlist(run!.run_id, query),
    enabled: !!run, placeholderData: keepPreviousData,
  });

  const update = (changes: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v) next.set(k, v);
    }
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };
  const sortBy = (key: string) => update({ sort: key, order: sort === key && order === "desc" ? "asc" : "desc" });
  const active = FILTERS.some((f) => filters[f.key].length) || review || params.get("q");

  if (!run) return <NoAssessment />;
  const cur = profileCurrency(run.profile);
  const data = q.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const SortHead = ({ k, label, numeric }: { k: string; label: string; numeric?: boolean }) => (
    <th className={numeric ? "num" : undefined} aria-sort={sort === k ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => sortBy(k)}>{label}{sort === k && (order === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}</button>
    </th>
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Monitoring <b>/ Customer watchlist</b></h1>
          <p className="hero-sub">{data ? `${data.total} customers match` : "Loading…"} · sorted by {sort.replace("_", " ")}, highest risk first by default</p>
        </div>
        <div className="actions">
          <a className="btn" href={api.watchlistCsvUrl(run.run_id, query)}><Download size={16} />Export CSV</a>
        </div>
      </div>

      <Card className="flush">
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, borderBottom: "1px solid var(--border)" }}>
          <form className="row wrap" onSubmit={(e) => { e.preventDefault(); update({ q: search.trim() || null }); }}>
            <div className="search" style={{ width: "min(420px, 100%)" }}>
              <Search size={16} aria-hidden />
              <label htmlFor="wl-search" className="sr-only">Search watchlist</label>
              <input id="wl-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Customer name or ID, then Enter" />
            </div>
            <div className="row" role="radiogroup" aria-label="Review status">
              {[["", "All"], ["unreviewed", "Not reviewed"], ["reviewed", "Reviewed"]].map(([v, l]) => (
                <button key={v} type="button" role="radio" aria-checked={review === v}
                  className={`filter-btn${review === v ? " active" : ""}`} onClick={() => update({ review: v || null })}>{l}</button>
              ))}
            </div>
            {q.isFetching && <Spinner />}
          </form>
          <div className="filters">
            {FILTERS.map((f) => (
              <MultiFilter key={f.key} label={f.label} options={data?.facets[f.key] ?? []} value={filters[f.key]}
                onChange={(v) => update({ [f.key]: v })} />
            ))}
            {active && <button className="btn ghost sm" onClick={() => setParams({}, { replace: true })}><X size={14} />Clear all</button>}
          </div>
        </div>

        {q.error ? <div style={{ padding: 16 }}><ErrorNote error={q.error} /></div> : !data ? (
          <div style={{ padding: 16 }} className="stack">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} height={40} />)}</div>
        ) : data.total === 0 ? (
          <Empty title="No customers match these filters">Try removing a filter or clearing the search.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <SortHead k="customer_name" label="Customer" />
                  <th>Product</th>
                  <SortHead k="total_outstanding" label="Outstanding" numeric />
                  <SortHead k="score" label="Warning score" />
                  <th>Band</th>
                  <th>Contributing indicators</th>
                  <SortHead k="current_dpd" label="DPD" numeric />
                  <SortHead k="confidence" label="Confidence" numeric />
                  <th>Monitoring status</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.customer_id} className="clickable" tabIndex={0}
                    onClick={() => navigate(`/customers/${r.customer_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/customers/${r.customer_id}`)}>
                    <td><div className="who"><span className="who-icon">{initials(r.customer_name)}</span>
                      <span><strong>{r.customer_name}</strong><small>{r.customer_id} · {r.segment} · {r.portfolio}</small></span></div></td>
                    <td className="small" style={{ minWidth: 150 }}>{r.main_product}{r.products.length > 1 && <span className="muted"> +{r.products.length - 1}</span>}</td>
                    <td className="num">{money(r.total_outstanding, cur)}</td>
                    <td><ScoreBar score={r.score} band={r.band} /></td>
                    <td><BandPill band={r.band} /></td>
                    <td>
                      <div className="row" style={{ gap: 4 }} title={r.top_factors.map((f) => `${f.name} (${f.points} pts)`).join(", ")}>
                        {r.top_factors.length ? <>
                          {r.top_factors.slice(0, 2).map((f) => <span key={f.signal_id} className="tag nowrap">{f.name}</span>)}
                          {r.signals_active > 2 && <span className="tag nowrap muted">+{r.signals_active - 2}</span>}
                        </> : <span className="muted small">{r.status === "Insufficient data" ? "Not enough history" : "None active"}</span>}
                      </div>
                    </td>
                    <td className="num">{r.current_dpd ? <span className="strong">{num(r.current_dpd)}</span> : <span className="faint">0</span>}</td>
                    <td className="num">{pct(r.confidence)}</td>
                    <td><div className="stack" style={{ gap: 4 }}><span className="small">{r.monitoring_status}</span><ReviewPill decision={r.review_decision} /></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && (
          <div className="pager">
            <span>Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}</span>
            <span className="spacer" />
            <button className="btn sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })} aria-label="Previous page"><ChevronLeft size={14} /></button>
            <span>Page {page} of {pages}</span>
            <button className="btn sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })} aria-label="Next page"><ChevronRight size={14} /></button>
          </div>
        )}
      </Card>
    </>
  );
}
