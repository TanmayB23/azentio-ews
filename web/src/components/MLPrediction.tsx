import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, FlaskConical, Info } from "lucide-react";
import { api } from "../api";
import { date, num } from "../format";
import { Card, ErrorNote, Skeleton } from "./ui";

function chance(value: number) {
  return value < .001 ? "<0.1%" : value > .999 ? ">99.9%" : `${(value * 100).toFixed(1)}%`;
}

export function MLPredictionCard({ runId, customerId }: { runId: string; customerId: string }) {
  const [allFactors, setAllFactors] = useState(false);
  const query = useQuery({ queryKey: ["ml-prediction", runId, customerId],
    queryFn: () => api.mlPrediction(runId, customerId), staleTime: Infinity, retry: 1 });
  const data = query.data;
  const factors = (data?.factors ?? []).filter(f => Math.abs(f.contribution) > .0005);
  const visible = allFactors ? factors : factors.slice(0, 3);
  const maximum = Math.max(...factors.map(f => Math.abs(f.contribution)), .0001);
  return (
    <Card title="Predicted serious delinquency (ML)" sub="Reaching 30+ DPD within the next 3 months"
      className="ml-card" end={<span className="pill neutral"><FlaskConical size={12} />Prototype</span>}>
      <div className="callout warn small" style={{ marginBottom: 14, gap: 8 }}>
        <Info size={16} style={{ flexShrink: 0 }} />
        <span>Synthetic-data prototype: the method is ready for real data, not evidence of predictive accuracy. The model can learn generator patterns.</span>
      </div>
      {query.isLoading && <Skeleton height={110} />}
      {query.error && <><ErrorNote error={query.error} /><button className="btn sm" onClick={() => query.refetch()}>Retry forecast</button></>}
      {data && (
        <>
          {data.status === "predicted" && data.probability !== null ? (
            <>
              <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
                <strong className="mono" style={{ fontSize: 34, letterSpacing: "-.04em" }}>{chance(data.probability)}</strong>
                <span className="muted small">model-estimated chance</span>
              </div>
              <p className="muted tiny">Forecast window: after {date(data.as_of)} through {date(data.horizon_end)}. Distinct from the rule score and data confidence.</p>
              <div className="stack" style={{ gap: 12, marginTop: 14 }}>
                {visible.map(f => (
                  <div key={f.signal_id}>
                    <div className="row small" style={{ gap: 8 }}>
                      {f.direction === "increases" ? <ArrowUpRight size={15} style={{ color: "var(--critical)" }} /> : <ArrowDownRight size={15} style={{ color: "var(--forest)" }} />}
                      <span style={{ flex: 1 }}>{f.name} <span className="faint tiny">{f.signal_id}</span></span>
                      <strong className="mono tiny" title="Signed TreeSHAP contribution in calibrated log-odds">
                        {f.contribution >= 0 ? "+" : ""}{num(f.contribution, 3)}
                      </strong>
                    </div>
                    <div className="muted tiny" style={{ marginLeft: 23, marginTop: 3 }}>
                      {f.value === null ? (f.applicable ? "Not evaluated" : "Not applicable") : `Observed value: ${num(f.value, 2)}`} &middot; {f.direction === "increases" ? "raises" : "lowers"} the model estimate
                    </div>
                    <div className="bar-track" style={{ marginLeft: 23, marginTop: 4, height: 4 }}><div className="bar-fill" style={{ width: `${Math.abs(f.contribution) / maximum * 100}%`, background: f.direction === "increases" ? "var(--critical)" : "var(--forest)" }} /></div>
                  </div>
                ))}
                {!factors.length && <p className="muted small">No material individual signal contributions in this forecast.</p>}
              </div>
              {factors.length > 3 && <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={() => setAllFactors(v => !v)}>{allFactors ? "Show leading factors" : "Show all model factors"}</button>}
              <p className="muted tiny" style={{ marginTop: 10 }}>Factors are TreeSHAP effects in log-odds, not percentage points or rule points. They describe the model, not causes.</p>
            </>
          ) : (
            <div role="status" className="stack" style={{ gap: 6 }}>
              <strong>{data.status === "already_delinquent" ? "Already 30+ DPD" : data.status === "insufficient_data" ? "Insufficient history" : "Forecast unavailable"}</strong>
              <p className="muted small">{data.status === "model_unavailable" ? "No compatible trained model is available for this assessment. The rule assessment remains available." : data.reason}</p>
            </div>
          )}
          {data.model && (
            <details className="ml-details" style={{ marginTop: 16 }}>
              <summary className="small" style={{ cursor: "pointer" }}>Model, evaluation and limitations</summary>
              <div className="stack tiny muted" style={{ marginTop: 10, gap: 8 }}>
                <span>{data.model.algorithm} &middot; {data.model.model_id}</span>
                <span>Trained {date(data.model.trained_at, true)} &middot; {data.model.split === "customer-demo" ? "Customer-disjoint synthetic holdout; same calendar period" : "Purged chronological holdout"}</span>
                <span>Calibration: {data.model.calibration.method}. Evidence of real-world calibration is not established.</span>
                <span>Held-out diagnostic: {data.model.splits.test.rows} monthly rows, {data.model.splits.test.customers} customers, {data.model.splits.test.positive_rows} positive outcomes.</span>
                <span>Brier loss {num(data.model.evaluation.brier_score, 4)}; constant-rate baseline {num(data.model.evaluation.constant_baseline_brier, 4)}. Lower is better. Synthetic diagnostics only.</span>
                {data.base_probability !== undefined && <span>Model reference estimate: {chance(data.base_probability)}. Full log-odds = reference {num(data.base_log_odds ?? 0, 3)} + all 15 factor effects.</span>}
                <ul style={{ margin: 0, paddingLeft: 16 }}>{data.model.limitations.map(note => <li key={note}>{note}</li>)}</ul>
                {data.prediction_id && <span>Saved forecast {data.prediction_id.slice(0, 8)}; original rule alert is unchanged.</span>}
              </div>
            </details>
          )}
        </>
      )}
    </Card>
  );
}
