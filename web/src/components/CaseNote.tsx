import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CheckCircle2, ClipboardCheck, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../api";
import { date } from "../format";
import { useWorkspace } from "../state";
import type { CaseNoteRecord, RecommendedAction, Signal } from "../types";
import { Card, ErrorNote, ReviewPill, Spinner } from "./ui";

export interface ReviewPrefill { decision: string; reason: string; noteId: number; key: number }

const OWNER_TONE: Record<string, string> = {
  Collections: "band-Critical", Credit: "band-High", "Credit committee": "band-High",
  "Relationship manager": "lime", Operations: "neutral",
};

export function RecommendedActions({ actions }: { actions: RecommendedAction[] }) {
  return (
    <Card title="Recommended actions" sub="From the intervention playbook · most urgent first">
      {actions.length === 0 ? (
        <p className="muted small row" style={{ gap: 8 }}><CheckCircle2 size={16} color="var(--low)" />
          No intervention needed. Routine monitoring continues.</p>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          {actions.map((a, i) => (
            <div key={a.action_id} className={`list-tile${i === 0 ? " selected" : ""}`} style={{ cursor: "default", alignItems: "flex-start" }}>
              <span className="who-icon" style={{ borderRadius: 10, flex: "none" }}><ClipboardCheck size={16} /></span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ display: "block", fontWeight: 500 }}>{a.title}</strong>
                <span className="row wrap" style={{ gap: 6, margin: "4px 0" }}>
                  <span className={`pill ${OWNER_TONE[a.owner] ?? "neutral"}`}>{a.owner}</span>
                  <span className="muted tiny row" style={{ gap: 4 }}><CalendarClock size={12} />by {date(a.due_date)}</span>
                </span>
                <small className="muted" style={{ display: "block" }}>{a.detail}</small>
                {a.reasons.length > 0 && <small className="faint" style={{ display: "block", marginTop: 4 }}>Why: {a.reasons.join("; ")}</small>}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Cites({ ids, signals }: { ids: string[]; signals: Map<string, Signal> }) {
  if (!ids.length) return null;
  return (
    <span className="row wrap" style={{ gap: 4, display: "inline-flex", marginLeft: 6 }}>
      {ids.map((id) => (
        <span key={id} className="tag mono" style={{ fontSize: 11, padding: "0 6px" }}
          title={signals.get(id)?.name ?? "Evidence record"}>{id}</span>
      ))}
    </span>
  );
}

export function CaseNoteCard({ runId, customerId, actions, signals, onUse }: {
  runId: string; customerId: string; actions: RecommendedAction[]; signals: Signal[];
  onUse: (p: ReviewPrefill) => void;
}) {
  const { config, analyst } = useWorkspace();
  const client = useQueryClient();
  const key = ["caseNotes", runId, customerId];
  const history = useQuery({ queryKey: key, queryFn: () => api.caseNotes(runId, customerId) });
  const draft = useMutation({
    mutationFn: (regenerate: boolean) => api.draftCaseNote(runId, customerId, { analyst, regenerate }),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  const ai = config?.ai;
  const record: CaseNoteRecord | undefined = draft.data ?? history.data?.[0];
  const bySignal = new Map(signals.map((s) => [s.signal_id, s]));
  const title = (id: string) => actions.find((a) => a.action_id === id)?.title ?? id;
  const sourceLabel = (r: CaseNoteRecord) => (r.source === "template" ? "Rules draft" : `AI draft · ${r.model ?? r.source}`);

  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Sparkles size={17} color="var(--forest)" />Case note</span>}
      sub={ai?.enabled ? `Drafted by ${ai.model} from this alert's evidence only` : (ai?.disabled_reason ?? "Drafted from the alert and playbook")}
      end={record && (
        <button className="btn sm" onClick={() => draft.mutate(true)} disabled={draft.isPending} title="Draft a new version">
          <RefreshCw size={14} />Regenerate
        </button>
      )}>
      {!record && !history.isLoading && (
        <div className="stack" style={{ gap: 10 }}>
          <p className="muted small">Get a short case note: what is happening, which evidence shows it, what to do next and what to ask the customer.
            It is a draft for you to check; it never changes the score.</p>
          <button className="btn primary" onClick={() => draft.mutate(false)} disabled={draft.isPending}>
            {draft.isPending ? <><Spinner />Drafting…</> : <><Sparkles size={16} />Draft case note</>}
          </button>
        </div>
      )}
      {draft.isPending && record && <Spinner label="Drafting a new version…" />}
      <ErrorNote error={draft.error ?? history.error} />
      {record && !draft.isPending && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 6 }}>
            <span className={`pill ${record.source === "template" ? "neutral" : "forest"}`}>{sourceLabel(record)}</span>
            {record.verification.status === "verified"
              ? <span className="pill lime" title="All citations and numbers were found in the alert">Checked against evidence</span>
              : <span className="pill band-Medium" title="Some citations or numbers were not found in the alert">Check before use</span>}
            <span className="muted tiny">{date(record.created_at, true)}{record.requested_by ? ` · ${record.requested_by}` : ""}
              {history.data && history.data.length > 1 ? ` · version ${history.data.length}` : ""}</span>
          </div>
          {record.error && <div className="callout warn small"><AlertTriangle size={16} />AI unavailable, so this was drafted from rules: {record.error}</div>}
          {record.verification.status === "check" && (
            <div className="callout warn small"><AlertTriangle size={16} /><span>
              {record.verification.unknown_citations.length > 0 && <>Citations not in the alert: {record.verification.unknown_citations.join(", ")}. </>}
              {record.verification.unverified_numbers.length > 0 && <>Numbers not found in the alert: {record.verification.unverified_numbers.join(", ")}. </>}
              {record.verification.dropped_actions.length > 0 && <>Removed actions not in the playbook: {record.verification.dropped_actions.join(", ")}.</>}
            </span></div>
          )}

          <p style={{ fontSize: 15 }}>{record.note.summary}</p>

          <div>
            <h4 className="small strong" style={{ marginBottom: 6 }}>Key findings</h4>
            <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
              {record.note.key_findings.map((f, i) => <li key={i}>{f.text}<Cites ids={f.cites} signals={bySignal} /></li>)}
            </ul>
          </div>

          {record.note.recommended_actions.length > 0 && (
            <div>
              <h4 className="small strong" style={{ marginBottom: 6 }}>Next steps</h4>
              <ol className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
                {record.note.recommended_actions.map((a) => <li key={a.action_id}><b>{title(a.action_id)}</b>: {a.reason}<Cites ids={a.cites} signals={bySignal} /></li>)}
              </ol>
            </div>
          )}

          <div className="grid cols-2" style={{ gap: 12 }}>
            {record.note.questions_for_customer.length > 0 && (
              <div className="kpi"><h4 className="small strong" style={{ marginBottom: 6 }}>Ask the customer</h4>
                <ul className="small" style={{ margin: 0, paddingLeft: 16 }}>{record.note.questions_for_customer.map((q) => <li key={q}>{q}</li>)}</ul></div>
            )}
            {record.note.data_gaps.length > 0 && (
              <div className="kpi"><h4 className="small strong" style={{ marginBottom: 6 }}>Data gaps</h4>
                <ul className="small" style={{ margin: 0, paddingLeft: 16 }}>{record.note.data_gaps.map((g) => <li key={g}>{g}</li>)}</ul></div>
            )}
          </div>

          <div className="row wrap" style={{ gap: 10, alignItems: "center" }}>
            <span className="small muted">Suggested decision</span><ReviewPill decision={record.note.suggested_decision} />
            <span className="small" style={{ flex: 1, minWidth: 200 }}>{record.note.suggested_decision_reason}</span>
          </div>
          {record.note.caveats.length > 0 && <p className="muted tiny">{record.note.caveats.join(" ")}</p>}

          <button className="btn dark" onClick={() => onUse({
            decision: record.note.suggested_decision,
            reason: `${record.note.summary} ${record.note.suggested_decision_reason}`.trim(),
            noteId: record.note_id, key: Date.now(),
          })}>
            Use in review
          </button>
          <p className="muted tiny">Copies the suggestion into the review form. You still choose the decision and edit the reason.</p>
        </div>
      )}
    </Card>
  );
}
