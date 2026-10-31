import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowLeft, CreditCard, Download, FileText, Info, Lock, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { BAND_HEX, BandPill, Card, Empty, ErrorNote, ReviewPill, ScoreRing, Skeleton, Tabs, Toast } from "../components/ui";
import { date, initials, money, monthLabel, num, pct, profileCurrency } from "../format";
import { useWorkspace } from "../state";
import type { CustomerDetail, Row, Signal } from "../types";
import { NoAssessment } from "./Overview";
import { MLPredictionCard } from "../components/MLPrediction";
import { CaseNoteCard, RecommendedActions, type ReviewPrefill } from "../components/CaseNote";
import { EvidenceCard } from "../components/EvidenceCard";

const PILLAR_HELP: Record<string, string> = {
  Repayment: "Late, partial and missed instalments; current days past due",
  "Cash flow": "Income and inflow trends, balances, outflows, bounced payments",
  Exposure: "Utilisation, new facilities, obligations vs inflows, credit inquiries",
  Business: "SME tax filing regularity and receivable days",
};
const STATUS_ORDER: Record<string, number> = { Active: 0, "No warning": 1, "Missing data": 2, "Not applicable": 3 };

function fmtValue(v: number | null) {
  if (v === null || v === undefined) return "—";
  return Math.abs(v) >= 100 ? num(v) : num(v, Number.isInteger(v) ? 0 : 1);
}

function SignalTable({ signals }: { signals: Signal[] }) {
  const [showAll, setShowAll] = useState(false);
  const sorted = [...signals].sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || b.points - a.points);
  const visible = showAll ? sorted : sorted.filter((s) => s.status === "Active");
  return (
    <>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Indicator</th><th>Area</th><th className="num">Measured</th><th className="num">Trigger → full</th><th>Strength</th><th className="num">Points</th><th>Status</th></tr></thead>
          <tbody>
            {visible.map((s) => (
              <tr key={s.signal_id}>
                <td style={{ minWidth: 200 }}><strong style={{ fontWeight: 500 }}>{s.name}</strong><div className="muted tiny">{s.signal_id}
                  {s.pillar === "UB" && s.evaluated && <> · percentile vs similar customers</>}
                  {s.pillar !== "UB" && s.evidence.length > 0 && <> · <span title={s.evidence.join(", ")} style={{ textDecoration: "underline dotted", cursor: "help" }}>
                    {s.evidence.length} evidence item{s.evidence.length > 1 ? "s" : ""}</span></>}
                  {s.reason_not_evaluated && <> · {s.reason_not_evaluated}</>}</div>
                  {s.pillar === "UB" && s.evidence.length > 0 && (
                    <ul className="tiny" style={{ margin: "4px 0 0", paddingLeft: 16, color: "var(--ink-2)" }}>
                      {s.evidence.map((e) => <li key={e}>{e}</li>)}
                    </ul>
                  )}</td>
                <td className="small">{s.pillar_name}</td>
                <td className="num">{fmtValue(s.value)}</td>
                <td className="num muted">{fmtValue(s.trigger)} → {fmtValue(s.saturation)}</td>
                <td style={{ minWidth: 110 }}><div className="bar-track"><div className="bar-fill" style={{ width: `${s.strength * 100}%` }} /></div></td>
                <td className="num strong">{s.points ? num(s.points, 1) : "—"}</td>
                <td><span className={`pill ${s.status === "Active" ? "band-High" : s.status === "No warning" ? "lime" : "neutral"}`}>{s.status}</span></td>
              </tr>
            ))}
            {visible.length === 0 && <tr><td colSpan={7} className="muted">No active warning signals for this customer.</td></tr>}
          </tbody>
        </table>
      </div>
      <button className="btn ghost sm" style={{ marginTop: 10 }} onClick={() => setShowAll((v) => !v)}>
        {showAll ? "Show active indicators only" : `Show all ${signals.length} indicators (including inactive and not evaluated)`}
      </button>
    </>
  );
}

type ChartTab = "repayment" | "cashflow" | "exposure" | "business";

function EvidenceCharts({ d, currency }: { d: CustomerDetail; currency: string }) {
  const isSme = d.sme.length > 0;
  const [tab, setTab] = useState<ChartTab>("repayment");
  const tabs: { id: ChartTab; label: string }[] = [
    { id: "repayment", label: "Repayments" }, { id: "cashflow", label: "Cash flow" }, { id: "exposure", label: "Exposure" },
    ...(isSme ? [{ id: "business" as ChartTab, label: "Business (SME)" }] : []),
  ];
  const axis = { tickLine: false, axisLine: false, fontSize: 11 };
  const money0 = (v: number) => money(v, currency);
  const repay = d.repayment_months.map((m) => ({ ...m, label: monthLabel(m.month), dpd: m.worst_dpd ?? 0 }));
  const tx = d.transactions.map((t) => ({ ...t, label: monthLabel(String(t.month)) }));
  const ex = d.exposure.map((t) => ({ ...t, label: monthLabel(String(t.month)) }));
  const sme = d.sme.map((t) => ({ ...t, month: String(t.month), label: monthLabel(String(t.month)), late: t.tax_filing_status === "Filed On Time" ? 0 : 1 }));
  const empty = (rows: unknown[], what: string) => rows.length === 0 &&
    <Empty title={`No ${what} data`}>This is recorded as missing evidence, not as risk.</Empty>;

  return (
    <Card title="Evidence over time" sub="Monthly history behind the signals">
      <Tabs label="Evidence" tabs={tabs} value={tab} onChange={setTab} />
      <div style={{ height: 260 }}>
        {tab === "repayment" && (empty(repay, "repayment") || (
          <ResponsiveContainer>
            <BarChart data={repay} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="#eef0eb" />
              <XAxis dataKey="label" {...axis} /><YAxis {...axis} label={{ value: "worst DPD", angle: -90, position: "insideLeft", fontSize: 11, dx: 18 }} />
              <Tooltip formatter={(v: number, n: string) => [v, n === "dpd" ? "Worst days past due" : n]}
                labelFormatter={(l, p) => { const m = p?.[0]?.payload; return m ? `${l} · ${m.instalments} instalments, ${m.late} late, ${m.partial} partial, ${m.unpaid} unpaid` : l; }} />
              <Bar dataKey="dpd" radius={[6, 6, 0, 0]} barSize={18}>
                {repay.map((m) => <Cell key={m.month} fill={m.unpaid ? BAND_HEX.Critical : m.dpd > 30 ? BAND_HEX.High : m.dpd > 0 ? BAND_HEX.Medium : "#a3e77f"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ))}
        {tab === "cashflow" && (empty(tx, "transaction") || (
          <ResponsiveContainer>
            <AreaChart data={tx} margin={{ top: 6, right: 8, left: 6, bottom: 0 }}>
              <defs>
                <linearGradient id="g-in" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#86d95c" stopOpacity={0.4} /><stop offset="100%" stopColor="#86d95c" stopOpacity={0} /></linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#eef0eb" />
              <XAxis dataKey="label" {...axis} /><YAxis {...axis} tickFormatter={money0} width={64} />
              <Tooltip formatter={(v: number, n: string) => [money(v, currency, false), n]} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" name="Income receipts" dataKey="income_receipts" stroke="#5cbf3a" strokeWidth={2} fill="url(#g-in)" />
              <Area type="monotone" name="Total outflows" dataKey="total_outflows" stroke="#0f3d2e" strokeWidth={1.6} fill="none" strokeDasharray="5 4" />
              <Area type="monotone" name="Average balance" dataKey="avg_balance" stroke="#c99512" strokeWidth={1.4} fill="none" />
            </AreaChart>
          </ResponsiveContainer>
        ))}
        {tab === "exposure" && (empty(ex, "exposure") || (
          <ResponsiveContainer>
            <LineChart data={ex} margin={{ top: 6, right: 8, left: 6, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="#eef0eb" />
              <XAxis dataKey="label" {...axis} />
              <YAxis yAxisId="l" {...axis} tickFormatter={money0} width={64} />
              <YAxis yAxisId="r" orientation="right" {...axis} domain={[0, 100]} unit="%" />
              <Tooltip formatter={(v: number, n: string) => [n === "Utilisation" ? `${num(v, 1)}%` : money(v, currency, false), n]} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Line yAxisId="r" type="monotone" name="Utilisation" dataKey="utilisation_pct" stroke="#e2711d" strokeWidth={2} dot={false} connectNulls={false} />
              <Line yAxisId="l" type="monotone" name="Monthly obligations" dataKey="monthly_obligations" stroke="#0f3d2e" strokeWidth={2} dot={false} />
              <Line yAxisId="l" type="monotone" name="Bureau obligations" dataKey="external_bureau_obligations" stroke="#86d95c" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ))}
        {tab === "business" && (
          <ResponsiveContainer>
            <BarChart data={sme} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="#eef0eb" />
              <XAxis dataKey="label" {...axis} /><YAxis {...axis} />
              <Tooltip formatter={(v: number, n: string) => [num(v, 1), n]} labelFormatter={(l, p) => `${l} · tax filing: ${p?.[0]?.payload?.tax_filing_status ?? "—"}`} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar name="Receivable days" dataKey="receivable_days" radius={[6, 6, 0, 0]} barSize={14}>
                {sme.map((m) => <Cell key={String(m.month)} fill={m.late ? BAND_HEX.High : "#a3e77f"} />)}
              </Bar>
              <Bar name="Payable days" dataKey="payable_days" fill="#0f3d2e" radius={[6, 6, 0, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
      {tab === "repayment" && <p className="muted tiny" style={{ marginTop: 8 }}>Bar colour: green on time · amber late · orange 30+ days · red unpaid instalment.</p>}
      {tab === "business" && <p className="muted tiny" style={{ marginTop: 8 }}>Orange receivable bars mark months whose tax return was filed late or not filed.</p>}
    </Card>
  );
}

function ReviewPanel({ d, runId, prefill }: { d: CustomerDetail; runId: string; prefill: ReviewPrefill | null }) {
  const { config, analyst, setAnalyst } = useWorkspace();
  const client = useQueryClient();
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [name, setName] = useState(analyst);
  const [noteId, setNoteId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!prefill) return;
    setDecision(prefill.decision); setReason(prefill.reason); setNoteId(prefill.noteId);
    document.getElementById("review")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [prefill]);
  const decisions = config?.decisions ?? [];
  const help: Record<string, string> = {
    "Continue Monitoring": "Risk understood; keep on routine watch",
    "Requires Investigation": "Contact customer / RM and gather facts",
    "False Positive": "Signals do not reflect real deterioration",
    "Escalate for Review": "Refer to credit committee or collections",
  };
  const save = useMutation({
    mutationFn: () => api.addReview(runId, d.result.customer_id, { decision, reason, analyst: name, ai_note_id: noteId }),
    onSuccess: () => {
      setAnalyst(name.trim());
      setReason(""); setDecision(""); setNoteId(null);
      setToast("Decision recorded. Original score and evidence unchanged.");
      client.invalidateQueries({ queryKey: ["customer", runId, d.result.customer_id] });
      client.invalidateQueries({ queryKey: ["summary", runId] });
      client.invalidateQueries({ queryKey: ["watchlist", runId] });
    },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const current = d.reviews[0];
  return (
    <Card title="Analyst review" sub="Record an initial decision for this alert" id="review"
      end={current ? <ReviewPill decision={current.decision} /> : <ReviewPill decision={null} />}>
      <form onSubmit={submit} className="stack" style={{ gap: 12 }}>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="stack">
          <legend className="sr-only">Decision</legend>
          {decisions.map((opt) => (
            <label key={opt} className={`list-tile${decision === opt ? " selected" : ""}`} style={{ padding: "10px 12px" }}>
              <input type="radio" name="decision" value={opt} checked={decision === opt} onChange={() => setDecision(opt)} className="sr-only" />
              <span className="radio" aria-hidden />
              <span><strong style={{ display: "block", fontWeight: 500 }}>{opt}</strong><small className="muted">{help[opt]}</small></span>
            </label>
          ))}
        </fieldset>
        {noteId !== null && (
          <p className="tiny row" style={{ gap: 6 }}><span className="pill lime">From case note #{noteId}</span>
            <button type="button" className="btn ghost sm" onClick={() => setNoteId(null)}>Unlink</button></p>
        )}
        <div className="field">
          <label htmlFor="reason">Reason <span className="faint">(required)</span></label>
          <textarea id="reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000}
            placeholder="What did you check, and why this decision?" />
        </div>
        <div className="field">
          <label htmlFor="analyst">Analyst</label>
          <input id="analyst" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" maxLength={120} />
        </div>
        <ErrorNote error={save.error} />
        <button className="btn primary block" disabled={!decision || !reason.trim() || !name.trim() || save.isPending}>
          {save.isPending ? "Saving…" : "Record decision"}
        </button>
        <p className="muted tiny row" style={{ gap: 6 }}><Lock size={12} />Decisions are appended; the original score and evidence can never be edited.</p>
      </form>
      {d.reviews.length > 0 && (
        <>
          <h4 style={{ margin: "18px 0 10px", fontSize: 14 }}>Decision history</h4>
          <div className="timeline">
            {d.reviews.map((r) => (
              <div key={r.review_id} className="timeline-item">
                <span className="tl-dot" />
                <div>
                  <div className="row wrap" style={{ gap: 6 }}><ReviewPill decision={r.decision} /><span className="muted tiny">{date(r.created_at, true)} · {r.analyst}</span>
                    {r.ai_note_id ? <span className="tag" style={{ fontSize: 11 }}>used case note #{r.ai_note_id}</span> : null}</div>
                  <p className="small" style={{ marginTop: 4 }}>{r.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      <Toast message={toast} onDone={() => setToast(null)} />
    </Card>
  );
}

function Facilities({ rows, currency }: { rows: Row[]; currency: string }) {
  return (
    <Card title="Facilities" sub={`${rows.length} active`}>
      <div className="stack" style={{ gap: 10 }}>
        {rows.map((f) => (
          <div key={String(f.loan_id)} className="list-tile" style={{ cursor: "default" }}>
            <span className="who-icon" style={{ borderRadius: 10, background: f.facility_type === "Revolving" ? "var(--forest)" : "var(--lime-soft)", color: f.facility_type === "Revolving" ? "var(--lime)" : "var(--forest)" }}>
              <CreditCard size={16} />
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong style={{ display: "block", fontWeight: 500 }}>{String(f.product_type)}</strong>
              <small className="muted">{String(f.loan_id)}{f.contract_type ? ` · ${f.contract_type}` : ""} · {String(f.facility_type)}</small>
            </span>
            <span style={{ textAlign: "right" }}>
              <strong className="mono" style={{ display: "block", fontWeight: 500 }}>{money(Number(f.outstanding_balance), currency)}</strong>
              <small className="muted">EMI {money(Number(f.instalment_amount), currency)}</small>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function RepaymentTable({ rows, currency }: { rows: Row[]; currency: string }) {
  return (
    <Card className="flush">
      <div className="card-head" style={{ padding: "18px 18px 0" }}><div><h3>Repayment history</h3><p className="sub">Most recent 36 instalments across all facilities</p></div></div>
      <div className="table-wrap" style={{ maxHeight: 380 }}>
        <table className="data">
          <thead><tr><th>Due</th><th>Facility</th><th className="num">Due amount</th><th className="num">Paid</th><th>Paid on</th><th className="num">DPD</th><th>Status</th><th>Exception</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const status = String(r.repayment_status);
              const tone = status === "Paid On Time" ? "lime" : status === "Paid Late" ? "band-Medium" : status === "Partially Paid" ? "band-High" : "band-Critical";
              return (
                <tr key={String(r.repayment_id)}>
                  <td className="small">{date(String(r.due_date))}</td>
                  <td className="small">{String(r.loan_id)}</td>
                  <td className="num">{money(Number(r.amount_due), currency, false)}</td>
                  <td className="num">{r.amount_paid === null ? "—" : money(Number(r.amount_paid), currency, false)}</td>
                  <td className="small">{r.payment_date ? date(String(r.payment_date)) : <span className="faint">Not paid</span>}</td>
                  <td className="num">{num(Number(r.dpd))}</td>
                  <td><span className={`pill ${tone}`}>{status}</span></td>
                  <td className="small">{r.exception_reason ? <>{String(r.exception_reason)} <span className="muted">({r.exception_evidence_available === "Y" ? "evidence" : "no evidence"})</span></> : <span className="faint">—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function CustomerPage() {
  const { customerId = "" } = useParams();
  const { run } = useWorkspace();
  const q = useQuery({
    queryKey: ["customer", run?.run_id, customerId], queryFn: () => api.customer(run!.run_id, customerId), enabled: !!run,
  });
  const [prefill, setPrefill] = useState<ReviewPrefill | null>(null);
  if (!run) return <NoAssessment />;
  if (q.error) return <><Link to="/watchlist" className="btn sm" style={{ alignSelf: "flex-start" }}><ArrowLeft size={14} />Watchlist</Link><ErrorNote error={q.error} /></>;
  if (!q.data) return <div className="stack"><Skeleton height={150} /><Skeleton height={300} /></div>;

  const d = q.data;
  const r = d.result;
  const c = d.customer;
  const cur = profileCurrency(run.profile);
  const insufficient = r.status === "Insufficient data";
  const pillars = ["Repayment", "Cash flow", "Exposure", "Business"];

  return (
    <>
      <div className="row wrap">
        <Link to="/watchlist" className="btn sm"><ArrowLeft size={14} />Watchlist</Link>
        <span className="spacer" />
        <a className="btn sm" href={api.alertUrl(run.run_id, r.customer_id)}><Download size={14} />Original alert (JSON)</a>
        <a className="btn sm dark" href="#review"><ShieldCheck size={14} />Review this alert</a>
      </div>

      <Card>
        <div className="row wrap" style={{ gap: 22, alignItems: "center" }}>
          <span className="avatar" style={{ width: 64, height: 64, fontSize: 20 }}>{initials(String(c.customer_name ?? r.customer_id))}</span>
          <div style={{ flex: 1, minWidth: 260 }}>
            <h1 style={{ fontSize: 26, fontWeight: 600 }}>{String(c.customer_name ?? r.customer_id)}</h1>
            <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
              <span className="tag">{r.customer_id}</span>
              {["customer_type", "employment_or_business_category", "segment", "portfolio_classification", "industry", "region"].map((k) =>
                c[k] ? <span key={k} className="tag">{String(c[k])}</span> : null)}
            </div>
            <p className="muted small" style={{ marginTop: 8 }}>
              Relationship manager {String(c.relationship_manager ?? "—")} · customer since {date(String(c.onboarding_date ?? ""))} ·
              origination rating {String(c.origination_rating ?? "—")}
            </p>
          </div>

        </div>
      </Card>

      <div className="grid cols-2">
        <Card title="Rule-based assessment" sub="0-100 monitoring score; higher means greater risk">
          <div className="row" style={{ gap: 18 }}>
            <ScoreRing score={r.score} band={r.band} />
            <div className="stack" style={{ gap: 8 }}>
              <BandPill band={r.band ?? "Insufficient data"} />
              <div><div className="stat-label">Monitoring status</div><div className="strong">{r.monitoring_status}</div></div>
              <div><div className="stat-label">Data confidence</div><div className="strong">{pct(r.confidence)}</div></div>
            </div>
          </div>
          <p className="muted tiny" style={{ marginTop: 14 }}>Deterministic signals and policy modifiers. The ML forecast is a separate estimate and does not change this score.</p>
        </Card>
        <MLPredictionCard key={`${run.run_id}:${r.customer_id}`} runId={run.run_id} customerId={r.customer_id} />
      </div>

      <div className={`callout ${insufficient ? "warn" : r.band === "Critical" || r.band === "High" ? "error" : "info"}`}>
        {insufficient ? <Info size={18} /> : <AlertTriangle size={18} />}
        <div>
          <strong style={{ fontWeight: 600 }}>Why this assessment: </strong>{r.summary}
          {r.modifiers.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{r.modifiers.map((m) => <li key={m} className="small">{m}</li>)}</ul>
          )}
        </div>
      </div>

      <div className="grid cols-main">
        <div className="stack">
          <CaseNoteCard runId={run.run_id} customerId={r.customer_id} actions={d.recommended_actions} signals={r.signals} onUse={setPrefill} />
          <Card title="Score breakdown" sub="Higher score = higher risk. Highest area counts in full, the next three add 35%, 15% and 10%; unusual behaviour (ML) adds up to 8 points.">
            <div className="grid cols-2" style={{ gap: 12 }}>
              {pillars.map((p) => {
                const v = r.pillar_scores[p];
                return (
                  <div key={p} className="kpi">
                    <div className="row"><span className="strong">{p}</span><span className="spacer" />
                      <span className="mono strong">{v === undefined ? <span className="faint small">not scored</span> : num(v)}</span></div>
                    <div className="bar-track" style={{ margin: "8px 0 6px" }}><div className="bar-fill" style={{ width: `${v ?? 0}%`, background: v && v >= 50 ? "var(--high)" : undefined }} /></div>
                    <p className="muted tiny">{PILLAR_HELP[p]}</p>
                  </div>
                );
              })}
            </div>
          </Card>
          <Card title="Contributing indicators" sub="Every signal's points add up to the score (before any minimum-score rule)">
            <SignalTable signals={r.signals} />
          </Card>
          <EvidenceCharts d={d} currency={cur} />
          <RepaymentTable rows={d.repayments} currency={cur} />
        </div>
        <div className="stack">
          <RecommendedActions actions={d.recommended_actions} />
          <ReviewPanel d={d} runId={run.run_id} prefill={prefill} />
          <EvidenceCard runId={run.run_id} customerId={r.customer_id} repayments={d.repayments} />
          <Facilities rows={d.facilities} currency={cur} />
          <Card title="Assessment record" sub="Preserved exactly as scored">
            <div className="stack small" style={{ gap: 6 }}>
              <div className="row"><span className="muted">As of</span><span className="spacer" />{date(r.as_of)}</div>
              <div className="row"><span className="muted">Rules version</span><span className="spacer" /><span className="tag">{r.rules_version}</span></div>
              <div className="row"><span className="muted">Alert ID</span><span className="spacer" />#{d.alert_id}</div>
              <a className="btn sm" style={{ marginTop: 6 }} href={api.alertUrl(run.run_id, r.customer_id)}><FileText size={14} />Download original evidence</a>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
