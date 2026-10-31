import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, Database, Download, FileText, ListChecks, Network, ShieldAlert, Upload } from "lucide-react";
import { api } from "../api";
import { BAND_HEX, BandPill, Card, Empty, ErrorNote, Skeleton, Tabs } from "../components/ui";
import { clusterBasis, date, initials, money, num, pct, profileCurrency, profileName } from "../format";
import { useWorkspace } from "../state";
import type { Band } from "../types";

export function NoAssessment() {
  return (
    <Card>
      <Empty icon={<Database size={24} />} title="No assessment yet"
        action={<Link to="/data" className="btn primary">Load a portfolio <ArrowRight size={16} /></Link>}>
        Load a sample portfolio or upload your own files, check the validation report, then run an assessment.
      </Empty>
    </Card>
  );
}

const BANDS: Band[] = ["Critical", "High", "Medium", "Low", "Insufficient data"];

export function Overview() {
  const { run, runsLoading } = useWorkspace();
  const navigate = useNavigate();
  const [chart, setChart] = useState<"threshold" | "signals">("threshold");
  const q = useQuery({ queryKey: ["summary", run?.run_id], queryFn: () => api.summary(run!.run_id), enabled: !!run });

  if (runsLoading) return <Skeleton height={320} />;
  if (!run) return <NoAssessment />;
  if (q.error) return <ErrorNote error={q.error} />;
  const s = q.data;
  const cur = profileCurrency(run.profile);
  const toBand = (b: Band) => navigate(`/watchlist?band=${encodeURIComponent(b)}`);

  const donut = BANDS.filter((b) => b !== "Insufficient data").map((b) => ({ band: b, value: s?.exposure_by_band[b] ?? 0 }));
  const reviewed = s?.reviews.reviewed ?? 0;
  const elevated = s?.reviews.elevated ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Overview <b>/ Portfolio risk</b></h1>
          <div className="hero-figure mono">{s ? money(s.exposure_at_risk, cur, false) : <Skeleton height={36} width={280} />}</div>
          <p className="hero-sub">
            Exposure held by {s ? s.elevated : "…"} High and Critical customers · {profileName(run.profile)} profile ·
            data as of {s ? date(s.as_of) : "…"}
          </p>
        </div>
        <div className="actions">
          <Link to="/watchlist" className="btn"><ListChecks size={16} />Open watchlist</Link>
          <Link to="/memo" className="btn"><FileText size={16} />Risk memo</Link>
          <Link to="/data" className="btn primary"><Upload size={16} />New assessment</Link>
        </div>
      </div>

      <div className="grid cols-overview">
        <Card title="Risk bands" sub={`${s?.customers ?? "…"} customers in this assessment`}>
          <div className="stack" style={{ gap: 10 }}>
            {BANDS.map((b) => (
              <button key={b} className="list-tile" onClick={() => toBand(b)} aria-label={`Show ${b} customers`}>
                <span className="legend-swatch" style={{ background: BAND_HEX[b], width: 10, height: 34, borderRadius: 4 }} />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <strong style={{ display: "block", fontWeight: 500 }}>{b}</strong>
                  <small className="muted">{money(s?.exposure_by_band[b], cur)} exposure</small>
                </span>
                <span className="stat-value mono" style={{ fontSize: 18 }}>{s ? s.bands[b] : "–"}</span>
              </button>
            ))}
          </div>
        </Card>

        <div className="stack">
          <Card>
            <div className="quick">
              <Link to="/watchlist?band=Critical&band=High&review=unreviewed"><ShieldAlert />Review queue</Link>
              <Link to="/portfolio"><Network />Clusters</Link>
              <a href={api.watchlistCsvUrl(run.run_id, {})}><Download />Export</a>
            </div>
            <div className="kpis" style={{ marginTop: 14, gridTemplateColumns: "1fr 1fr" }}>
              <div><div className="stat-label">Total exposure</div><div className="stat-value mono">{money(s?.total_exposure, cur)}</div></div>
              <div><div className="stat-label">Avg. data confidence</div><div className="stat-value mono">{pct(s?.average_confidence)}</div></div>
            </div>
          </Card>
          <Card title="Review progress" sub="High and Critical alerts with an analyst decision">
            <div className="progress" role="img" aria-label={`${reviewed} of ${elevated} reviewed`}>
              <span className="done" style={{ flex: Math.max(reviewed, 0.0001) }} />
              <span className="rest" style={{ flex: Math.max(elevated - reviewed, 0.0001) }} />
            </div>
            <div className="row small" style={{ marginTop: 10 }}>
              <span className="muted">{reviewed} of {elevated} reviewed</span>
              <span className="spacer" />
              <strong>{elevated ? Math.round((reviewed / elevated) * 100) : 0}%</strong>
            </div>
            {s && s.actions.customers_with_actions > 0 && (
              <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                <div className="stat-label" style={{ marginBottom: 6 }}>Open actions by owner</div>
                {Object.entries(s.actions.by_owner).map(([owner, n]) => (
                  <div key={owner} className="row small" style={{ padding: "2px 0" }}><span>{owner}</span><span className="spacer" /><strong className="mono">{n}</strong></div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <Card title={chart === "threshold" ? "Customers above each score" : "Most common warning signals"}
          sub={chart === "threshold" ? "How many customers a watch threshold would flag (higher score = riskier)" : "Customers with each signal active"}>
          <Tabs label="Chart" value={chart} onChange={setChart}
            tabs={[{ id: "threshold", label: "By threshold" }, { id: "signals", label: "Signals" }]} />
          <div style={{ height: 230 }}>
            {!s ? <Skeleton height={230} /> : chart === "threshold" ? (
              <ResponsiveContainer>
                <AreaChart data={s.thresholds} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="g-score" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#86d95c" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="#86d95c" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#eef0eb" />
                  <XAxis dataKey="threshold" type="number" domain={[5, 100]} ticks={[5, 25, 50, 75, 100]} tickLine={false} axisLine={false} fontSize={11} />
                  <YAxis tickLine={false} axisLine={false} fontSize={11} allowDecimals={false} />
                  <Tooltip formatter={(v: number, _n, p) => [`${v} customers · ${money(p.payload.exposure, cur)}`, "At or above"]}
                    labelFormatter={(t) => `Score ≥ ${t}`} />
                  {[25, 50, 75].map((t) => <ReferenceLine key={t} x={t} stroke="#d7dbd2" strokeDasharray="4 4"
                    label={{ value: t === 25 ? "Medium" : t === 50 ? "High" : "Critical", position: "insideTopRight", fontSize: 10, fill: "#76807a" }} />)}
                  <Area type="monotone" dataKey="customers" stroke="#5cbf3a" strokeWidth={2} fill="url(#g-score)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer>
                <BarChart data={s.top_signals} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={150} tickLine={false} axisLine={false} fontSize={12} />
                  <Tooltip formatter={(v: number) => [`${v} customers`, "Active"]} />
                  <Bar dataKey="customers" fill="#a3e77f" radius={[0, 6, 6, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>
      </div>

      <div className="grid cols-overview-2">
        <Card className="flush" title={undefined}>
          <div className="card-head" style={{ padding: "18px 18px 0" }}>
            <div><h3>Priority customers</h3><p className="sub">Highest risk first · select a row to open evidence</p></div>
            <div className="end"><Link to="/watchlist" className="btn sm">View all <ArrowRight size={14} /></Link></div>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Customer</th><th className="num">Score</th><th>Band</th></tr></thead>
              <tbody>
                {(s?.priority ?? []).map((r) => (
                  <tr key={r.customer_id} className="clickable" tabIndex={0}
                    onClick={() => navigate(`/customers/${r.customer_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/customers/${r.customer_id}`)}>
                    <td><div className="who"><span className="who-icon">{initials(r.customer_name)}</span>
                      <span style={{ minWidth: 0 }}><strong style={{ maxWidth: 210 }}>{r.customer_name}</strong><small>{r.customer_id} · {money(r.total_outstanding, cur)} · {r.review_decision ?? "Not reviewed"}</small></span></div></td>
                    <td className="num strong">{num(r.score)}</td>
                    <td><BandPill band={r.band} /></td>
                  </tr>
                ))}
                {s && s.priority.length === 0 && <tr><td colSpan={3} className="muted">No High or Critical customers.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="stack">
          <Card title="Exposure by band" sub="Outstanding balance held in each band">
            <div className="row" style={{ alignItems: "center", gap: 16 }}>
              <div style={{ width: 170, height: 170, position: "relative", flex: "none" }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={donut} dataKey="value" nameKey="band" innerRadius={58} outerRadius={80} paddingAngle={2} stroke="none">
                      {donut.map((d) => <Cell key={d.band} fill={BAND_HEX[d.band]} />)}
                    </Pie>
                    <Tooltip formatter={(v: number, n: string) => [money(v, cur), n]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center", pointerEvents: "none" }}>
                  <div><div className="muted small">At risk</div><div className="strong mono">{money(s?.exposure_at_risk, cur)}</div></div>
                </div>
              </div>
              <div className="legend">
                {donut.map((d) => (
                  <div key={d.band} className="legend-item">
                    <span className="legend-swatch" style={{ background: BAND_HEX[d.band] }} />
                    <span>{d.band}</span>
                    <span className="muted mono small" style={{ marginLeft: "auto", paddingLeft: 10 }}>
                      {s && s.total_exposure ? pct(d.value / s.total_exposure) : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </Card>
          <Card>
            <Link to="/data" className="row" style={{ gap: 14 }}>
              <span className="who-icon" style={{ width: 46, height: 46, background: "var(--forest)", color: "var(--lime)" }}><Database size={20} /></span>
              <span style={{ flex: 1 }}>
                <strong style={{ display: "block", fontWeight: 500 }}>Data quality</strong>
                <span className="muted small">
                  {s ? `${s.quality.issue_count} issues · ${s.quality.action.quarantined} quarantined · ${s.quality.action.repaired} repaired` : "…"}
                </span>
              </span>
              <ArrowRight size={16} className="faint" />
            </Link>
          </Card>
        </div>

        <Card title="Emerging clusters" sub="Segments where risk is concentrated"
          end={<Link to="/portfolio" className="btn sm">All</Link>}>
          <div className="stack" style={{ gap: 10 }}>
            {(s?.clusters ?? []).map((c) => (
              <Link key={`${c.dimension}-${c.value}`} to={`/portfolio?cluster=${encodeURIComponent(`${c.dimension}::${c.value}`)}`} className="list-tile">
                <span className="who-icon"><Network size={16} /></span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <strong style={{ display: "block", fontWeight: 500 }}>{c.value.replace("|", " · ")}</strong>
                  <small className="muted" style={{ display: "block" }}>{clusterBasis(c)}</small>
                  <small className="faint">{c.n_elevated} of {c.n_customers} Medium or above (×{num(c.elevated_lift, 1)})</small>
                </span>
                <span className="pill lime mono" title={`${clusterBasis(c)}: ${num(c.lift, 1)} times the portfolio rate`}>×{num(c.lift, 1)}</span>
              </Link>
            ))}
            {s && s.clusters.length === 0 && <p className="muted">No significant concentrations detected.</p>}
          </div>
          <Link to="/portfolio" className="btn primary block" style={{ marginTop: 14 }}>Investigate clusters</Link>
        </Card>
      </div>
    </>
  );
}
