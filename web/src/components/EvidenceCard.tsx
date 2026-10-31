import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, Upload } from "lucide-react";
import { api } from "../api";
import { date } from "../format";
import { useWorkspace } from "../state";
import type { AIRecord, EvidenceCheck, Row } from "../types";
import { AIStatusNotes } from "./ClusterBriefing";
import { Card, ErrorNote, Spinner } from "./ui";

const VERDICT_TONE: Record<string, string> = {
  supports: "lime", "partially supports": "band-Medium", "does not support": "band-Critical",
  unreadable: "neutral", "not assessed": "neutral",
};

function Decision({ runId, customerId, check, repaymentId }: {
  runId: string; customerId: string; check: AIRecord<EvidenceCheck>; repaymentId: string;
}) {
  const { analyst } = useWorkspace();
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (accepted: boolean) => api.decideEvidence(runId, customerId, {
      repayment_id: repaymentId, accepted, note, analyst: analyst || "analyst", output_id: check.output_id,
    }),
    onSuccess: () => { setNote(""); client.invalidateQueries({ queryKey: ["evidenceDecisions", runId, customerId] }); },
  });
  return (
    <div className="stack" style={{ gap: 6 }}>
      <input className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}
        placeholder={`Your note on ${repaymentId} (required)`} aria-label="Evidence decision note" />
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn sm dark" disabled={!note.trim() || decide.isPending} onClick={() => decide.mutate(true)}>Accept evidence</button>
        <button className="btn sm" disabled={!note.trim() || decide.isPending} onClick={() => decide.mutate(false)}>Reject evidence</button>
      </div>
      <ErrorNote error={decide.error} />
    </div>
  );
}

export function EvidenceCard({ runId, customerId, repayments }: { runId: string; customerId: string; repayments: Row[] }) {
  const { config, analyst } = useWorkspace();
  const client = useQueryClient();
  const late = repayments.filter((r) => Number(r.dpd) > 0);
  const [repaymentId, setRepaymentId] = useState(String(late[0]?.repayment_id ?? ""));
  const [claim, setClaim] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const checks = useQuery({ queryKey: ["evidenceChecks", runId, customerId], queryFn: () => api.evidenceChecks(runId, customerId) });
  const decisions = useQuery({ queryKey: ["evidenceDecisions", runId, customerId], queryFn: () => api.evidenceDecisions(runId, customerId) });
  const check = useMutation({
    mutationFn: () => api.checkEvidence(runId, customerId, file!, repaymentId, claim, analyst),
    onSuccess: () => { setFile(null); client.invalidateQueries({ queryKey: ["evidenceChecks", runId, customerId] }); },
  });

  return (
    <Card title={<span className="row" style={{ gap: 8 }}><FileCheck2 size={17} color="var(--forest)" />Evidence check</span>}
      sub={config?.ai?.enabled ? "AI reads a supporting document; you decide whether it counts" : "Store a supporting document and record your decision"}>
      {late.length === 0 ? <p className="muted small">No late instalments for this customer, so there is nothing to evidence.</p> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="field">
            <label htmlFor="ev-rep">Late instalment</label>
            <select id="ev-rep" className="input chip-select" value={repaymentId} onChange={(e) => setRepaymentId(e.target.value)}>
              {late.slice(0, 20).map((r) => (
                <option key={String(r.repayment_id)} value={String(r.repayment_id)}>
                  {String(r.repayment_id)} · due {date(String(r.due_date))} · {String(r.dpd)} days late{r.exception_reason ? ` · ${r.exception_reason}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ev-claim">What the customer says</label>
            <input id="ev-claim" className="input" value={claim} onChange={(e) => setClaim(e.target.value)} maxLength={500}
              placeholder="e.g. Salary paid late by employer" />
          </div>
          <div className="row wrap" style={{ gap: 8 }}>
            <button className="btn" onClick={() => input.current?.click()}><Upload size={16} />{file ? file.name : "Choose document"}</button>
            <input ref={input} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button className="btn primary" disabled={!file || check.isPending} onClick={() => check.mutate()}>
              {check.isPending ? <><Spinner />Reading…</> : "Check document"}
            </button>
          </div>
          <p className="muted tiny">PDF or image, up to 10 MB. {config?.ai?.enabled ? "The document and the late instalments (no customer name) are sent to the AI model." : "No AI key: the document is stored for you to read."}</p>
          <ErrorNote error={check.error ?? checks.error} />
        </div>
      )}

      {(checks.data ?? []).slice(0, 3).map((c) => (
        <div key={c.output_id} className="kpi stack" style={{ gap: 8, marginTop: 12, background: "var(--surface)" }}>
          <AIStatusNotes record={c} />
          <div className="row wrap" style={{ gap: 6 }}>
            <span className={`pill ${VERDICT_TONE[c.output.verdict] ?? "neutral"}`}>{c.output.verdict}</span>
            <span className="small strong">{c.output.document_type}</span>
            <span className="muted tiny">{c.output.issuer} · {c.output.document_date} · {c.output.file_name}</span>
          </div>
          <p className="small">{c.output.summary}</p>
          {c.output.matched_details.length > 0 && <p className="tiny"><b>Matches:</b> {c.output.matched_details.join("; ")}</p>}
          {c.output.concerns.length > 0 && <p className="tiny" style={{ color: "var(--high)" }}><b>Concerns:</b> {c.output.concerns.join("; ")}</p>}
          <Decision runId={runId} customerId={customerId} check={c}
            repaymentId={c.output.repayment_ids[0] ?? c.output.requested_repayment_id ?? repaymentId} />
        </div>
      ))}

      {(decisions.data ?? []).length > 0 && (
        <>
          <h4 style={{ margin: "16px 0 8px", fontSize: 14 }}>Evidence decisions</h4>
          <div className="timeline">
            {decisions.data!.map((d) => (
              <div key={d.decision_id} className="timeline-item"><span className="tl-dot" />
                <div>
                  <div className="row wrap" style={{ gap: 6 }}>
                    <span className={`pill ${d.accepted ? "lime" : "band-Critical"}`}>{d.accepted ? "Accepted" : "Rejected"}</span>
                    <span className="small">{d.repayment_id}</span>
                    <span className="muted tiny">{date(d.created_at, true)} · {d.analyst}</span>
                  </div>
                  <p className="small" style={{ marginTop: 4 }}>{d.note}</p>
                </div>
              </div>
            ))}
          </div>
          <p className="muted tiny" style={{ marginTop: 8 }}>Recorded for the audit trail; the saved score is not changed.</p>
        </>
      )}
    </Card>
  );
}
