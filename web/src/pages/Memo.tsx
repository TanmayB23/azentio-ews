import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../api";
import { AIStatusNotes } from "../components/ClusterBriefing";
import { Card, Empty, ErrorNote, Spinner } from "../components/ui";
import { date, profileName } from "../format";
import { useWorkspace } from "../state";
import type { RiskMemo } from "../types";
import { NoAssessment } from "./Overview";

function Section({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 style={{ fontSize: 15, marginBottom: 8 }}>{title}</h3>
      <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>{items.map((i) => <li key={i}>{i}</li>)}</ul>
    </div>
  );
}

export function MemoPage() {
  const { run, analyst } = useWorkspace();
  const client = useQueryClient();
  const key = ["memos", run?.run_id];
  const history = useQuery({ queryKey: key, queryFn: () => api.memos(run!.run_id), enabled: !!run });
  const draft = useMutation({
    mutationFn: (regenerate: boolean) => api.memo(run!.run_id, { analyst, regenerate }),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  if (!run) return <NoAssessment />;
  const record = draft.data ?? history.data?.[0];
  const m = record?.output as RiskMemo | undefined;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Reporting <b>/ Portfolio risk memo</b></h1>
          <p className="hero-sub">A management summary of this assessment, compared with the previous assessment of the same portfolio.</p>
        </div>
        <div className="actions">
          {record && <a className="btn" href={api.memoUrl(run.run_id, record.output_id)}><Download size={16} />Download (.md)</a>}
          <button className="btn primary" onClick={() => draft.mutate(!!record)} disabled={draft.isPending}>
            {draft.isPending ? <Spinner /> : record ? <RefreshCw size={16} /> : <Sparkles size={16} />}
            {record ? "Regenerate" : "Draft memo"}
          </button>
        </div>
      </div>
      <ErrorNote error={draft.error ?? history.error} />
      {!record && !history.isLoading && !draft.isPending && (
        <Card><Empty icon={<FileText size={22} />} title="No memo yet"
          action={<button className="btn primary" onClick={() => draft.mutate(false)}><Sparkles size={16} />Draft memo</button>}>
          Drafts a one-page summary for {profileName(run.profile)} · {run.dataset_label}: main risks, changes since the last assessment, clusters, actions due and data quality.
        </Empty></Card>
      )}
      {draft.isPending && <Card><Spinner label="Drafting the memo…" /></Card>}
      {record && m && !draft.isPending && (
        <Card>
          <div className="stack" style={{ gap: 18, maxWidth: 820 }}>
            <AIStatusNotes record={record} />
            <div>
              <h2 style={{ fontSize: 22, fontWeight: 600 }}>{m.title}</h2>
              <p style={{ fontSize: 16, marginTop: 6 }}>{m.headline}</p>
              <p className="muted tiny" style={{ marginTop: 4 }}>
                {"compared_with" in record && (record as { compared_with?: { created_at: string } | null }).compared_with
                  ? `Compared with the assessment of ${date((record as { compared_with: { created_at: string } }).compared_with.created_at, true)}`
                  : `Requested by ${record.requested_by} · ${date(record.created_at, true)}`}
              </p>
            </div>
            <Section title="Key points" items={m.key_points.map((p) => p.text)} />
            <Section title="Changes since the last assessment" items={m.changes_since_last} />
            <Section title="Risk clusters" items={m.clusters} />
            <Section title="Actions due" items={m.actions_due} />
            <div><h3 style={{ fontSize: 15, marginBottom: 8 }}>Data quality</h3><p>{m.data_quality}</p></div>
            <Section title="Recommendations" items={m.recommendations} />
          </div>
        </Card>
      )}
      {history.data && history.data.length > 1 && (
        <p className="muted tiny">{history.data.length} versions saved for this assessment; earlier versions stay in the audit store.</p>
      )}
    </>
  );
}
