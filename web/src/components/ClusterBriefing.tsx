import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../api";
import { date } from "../format";
import { useWorkspace } from "../state";
import type { AIRecord, ClusterBriefing as Briefing } from "../types";
import { Card, ErrorNote, Spinner } from "./ui";

function SourcePills({ record }: { record: AIRecord<unknown> }) {
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      <span className={`pill ${record.source === "template" ? "neutral" : "forest"}`}>
        {record.source === "template" ? "Rules draft" : `AI draft · ${record.model ?? record.source}`}
      </span>
      {record.verification.status === "verified"
        ? <span className="pill lime">Checked against data</span>
        : <span className="pill band-Medium">Check before use</span>}
      <span className="muted tiny">{date(record.created_at, true)}</span>
    </div>
  );
}

export function AIStatusNotes({ record }: { record: AIRecord<unknown> }) {
  const v = record.verification as Record<string, unknown>;
  const issues = Object.entries(v).filter(([k, val]) => k !== "status" && Array.isArray(val) && val.length > 0)
    .map(([k, val]) => `${k.replace(/_/g, " ")}: ${(val as unknown[]).join(", ")}`);
  return (
    <>
      <SourcePills record={record} />
      {record.error && <div className="callout warn small"><AlertTriangle size={16} />AI unavailable, drafted from rules: {record.error}</div>}
      {issues.length > 0 && <div className="callout warn small"><AlertTriangle size={16} />{issues.join(" · ")}</div>}
    </>
  );
}

export function ClusterBriefingCard({ runId, dimension, value }: { runId: string; dimension: string; value: string }) {
  const { analyst } = useWorkspace();
  const client = useQueryClient();
  const key = ["briefings", runId, dimension, value];
  const history = useQuery({ queryKey: key, queryFn: () => api.clusterBriefings(runId, dimension, value) });
  const draft = useMutation({
    mutationFn: (regenerate: boolean) => api.clusterBriefing(runId, { dimension, value, analyst, regenerate }),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  const record = draft.data ?? history.data?.[0];
  const b = record?.output as Briefing | undefined;

  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Sparkles size={17} color="var(--forest)" />Cluster briefing</span>}
      sub="For the credit committee: is this isolated or segment-wide, and what to do"
      end={record && <button className="btn sm" onClick={() => draft.mutate(true)} disabled={draft.isPending}><RefreshCw size={14} />Regenerate</button>}>
      {!record && !history.isLoading && (
        <button className="btn primary block" onClick={() => draft.mutate(false)} disabled={draft.isPending}>
          {draft.isPending ? <><Spinner />Drafting…</> : <><Sparkles size={16} />Draft briefing</>}
        </button>
      )}
      {draft.isPending && record && <Spinner label="Drafting a new version…" />}
      <ErrorNote error={draft.error ?? history.error} />
      {record && b && !draft.isPending && (
        <div className="stack" style={{ gap: 12 }}>
          <AIStatusNotes record={record} />
          <p style={{ fontSize: 15, fontWeight: 500 }}>{b.headline}</p>
          <p className="small">{b.pattern}</p>
          <div className={`callout ${b.segment_wide ? "error" : "info"} small`}>
            <span><b>{b.segment_wide ? "Segment-wide" : "Looks isolated"}.</b> {b.segment_wide_reason}</span>
          </div>
          {b.shared_drivers.length > 0 && (
            <div><h4 className="small strong" style={{ marginBottom: 6 }}>Shared drivers</h4>
              <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
                {b.shared_drivers.map((d, i) => <li key={i}>{d.text} {d.cites.map((c) => <span key={c} className="tag mono" style={{ fontSize: 11, padding: "0 6px" }}>{c}</span>)}</li>)}
              </ul></div>
          )}
          {b.segment_actions.length > 0 && (
            <div><h4 className="small strong" style={{ marginBottom: 6 }}>Segment actions</h4>
              <ol className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>{b.segment_actions.map((a) => <li key={a}>{a}</li>)}</ol></div>
          )}
          {b.customers_to_prioritise.length > 0 && (
            <div className="row wrap" style={{ gap: 6 }}><span className="small muted">Review first:</span>
              {b.customers_to_prioritise.map((c) => <Link key={c} to={`/customers/${c}`} className="tag">{c}</Link>)}</div>
          )}
          {b.caveats.length > 0 && <p className="muted tiny">{b.caveats.join(" ")}</p>}
        </div>
      )}
    </Card>
  );
}
