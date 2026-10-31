import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Network } from "lucide-react";
import { api } from "../api";
import { BandPill, Card, Empty, ErrorNote, ReviewPill, Skeleton } from "../components/ui";
import { clusterBasis, initials, money, num, pct, profileCurrency } from "../format";
import { useWorkspace } from "../state";
import { NoAssessment } from "./Overview";

export function Portfolio() {
  const { run } = useWorkspace();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const clusters = useQuery({ queryKey: ["clusters", run?.run_id], queryFn: () => api.clusters(run!.run_id), enabled: !!run });
  const summary = useQuery({ queryKey: ["summary", run?.run_id], queryFn: () => api.summary(run!.run_id), enabled: !!run });

  if (!run) return <NoAssessment />;
  if (clusters.error) return <ErrorNote error={clusters.error} />;
  const cur = profileCurrency(run.profile);
  const list = clusters.data ?? [];
  const key = (c: { dimension: string; value: string }) => `${c.dimension}::${c.value}`;
  const selected = list.find((c) => key(c) === params.get("cluster")) ?? list[0];
  const pillars = Object.entries(summary.data?.pillar_prevalence ?? {}).map(([pillar, customers]) => ({ pillar, customers }));

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Portfolio <b>/ Concentrations & clusters</b></h1>
          <p className="hero-sub">Groups by product, industry, region, segment and portfolio where emerging risk is over-represented</p>
        </div>
      </div>

      <div className="grid cols-main">
        <Card title="Detected clusters" sub="Ranked by statistical strength. ×N = how many times more common the named pattern is here than across the book">
          {!clusters.data ? <Skeleton height={240} /> : list.length === 0 ? (
            <Empty icon={<Network size={22} />} title="No significant clusters">Risk is not concentrated in any segment beyond what chance explains.</Empty>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              {list.map((c) => (
                <button key={key(c)} className={`list-tile${selected && key(selected) === key(c) ? " selected" : ""}`}
                  onClick={() => setParams({ cluster: key(c) }, { replace: true })}>
                  <span className="radio" />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <strong style={{ display: "block", fontWeight: 500 }}>{c.value.replace("|", " · ")}</strong>
                    <small className="muted" style={{ display: "block" }}>{clusterBasis(c)}</small>
                    <small className="faint">{c.dimension} · {c.n_elevated} of {c.n_customers} Medium or above (×{num(c.elevated_lift, 1)})</small>
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <span className="pill lime mono" title={`${clusterBasis(c)}: ${num(c.lift, 1)} times the portfolio rate`}>×{num(c.lift, 1)}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </Card>
        <div className="stack">
          <Card title="Warning areas across the book" sub="Customers with at least one active signal in each area">
            <div style={{ height: 200 }}>
              {!summary.data ? <Skeleton height={200} /> : (
                <ResponsiveContainer>
                  <BarChart data={pillars} margin={{ top: 6, right: 6, left: -20, bottom: 0 }}>
                    <XAxis dataKey="pillar" tickLine={false} axisLine={false} fontSize={12} />
                    <YAxis tickLine={false} axisLine={false} fontSize={11} allowDecimals={false} />
                    <Tooltip formatter={(v: number) => [`${v} customers`, "With active signal"]} />
                    <Bar dataKey="customers" fill="#0f3d2e" radius={[8, 8, 0, 0]} barSize={34} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>
          {selected && (
            <Card className="dark">
              <p className="muted small">Selected cluster</p>
              <h3 style={{ fontSize: 20, margin: "4px 0 4px", color: "#fff" }}>{selected.value.replace("|", " · ")}</h3>
              <p className="small" style={{ color: "var(--lime)", marginBottom: 12 }}>
                Flagged because: {clusterBasis(selected)} (×{num(selected.lift, 1)})
              </p>
              <div className="grid cols-2" style={{ gap: 12 }}>
                <div><div className="muted small">Exposure</div><div className="stat-value mono">{money(selected.exposure, cur)}</div></div>
                <div><div className="muted small">Elevated exposure</div><div className="stat-value mono" style={{ color: "var(--lime)" }}>{money(selected.elevated_exposure, cur)}</div></div>
                <div><div className="muted small">Medium or above</div><div className="stat-value mono">{selected.n_elevated} / {selected.n_customers}</div>
                  <div className="muted tiny">{pct(selected.n_elevated / selected.n_customers)} vs {pct(selected.n_elevated / selected.n_customers / (selected.elevated_lift || 1))} of the book (×{num(selected.elevated_lift, 1)})</div></div>
                <div><div className="muted small">Significance</div><div className="stat-value mono">p {selected.p_value < 0.0001 ? "< 0.0001" : num(selected.p_value, 4)}</div></div>
              </div>
              <p className="small" style={{ marginTop: 12, color: "#cfe3d8" }}>Most common signals in this group: {selected.top_signal_names.join(", ")}</p>
            </Card>
          )}
        </div>
      </div>

      {selected && (
        <Card className="flush">
          <div className="card-head" style={{ padding: "18px 18px 0" }}>
            <div><h3>Customers in {selected.value.replace("|", " · ")}</h3><p className="sub">Is the pattern isolated or segment-wide? Compare bands and indicators below.</p></div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Customer</th><th>Product</th><th className="num">Outstanding</th><th className="num">Score</th><th>Band</th><th>Top indicators</th><th>Review</th></tr></thead>
              <tbody>
                {selected.members.map((r) => (
                  <tr key={r.customer_id} className="clickable" tabIndex={0} onClick={() => navigate(`/customers/${r.customer_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/customers/${r.customer_id}`)}>
                    <td><div className="who"><span className="who-icon">{initials(r.customer_name)}</span><span><strong>{r.customer_name}</strong><small>{r.customer_id} · {r.region}</small></span></div></td>
                    <td className="small">{r.main_product}</td>
                    <td className="num">{money(r.total_outstanding, cur)}</td>
                    <td className="num strong">{num(r.score)}</td>
                    <td><BandPill band={r.band} /></td>
                    <td><div className="row wrap" style={{ gap: 4 }}>{r.top_factors.map((f) => <span key={f.signal_id} className="tag">{f.name}</span>)}</div></td>
                    <td><ReviewPill decision={r.review_decision} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
