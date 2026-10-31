import { useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, FileSpreadsheet, Play, Upload, X } from "lucide-react";
import { api } from "../api";
import { Card, Empty, ErrorNote, MultiFilter, Skeleton, Spinner, Tabs } from "../components/ui";
import { date, num, profileName } from "../format";
import { useWorkspace } from "../state";
import type { DatasetMeta, RunMeta, ValidationIssue } from "../types";

const ACCEPT = ".csv,.xlsx,.xls,.json";

function SourcePicker({ onLoaded }: { onLoaded: (d: DatasetMeta) => void }) {
  const { config } = useWorkspace();
  const [mode, setMode] = useState<"sample" | "upload">("sample");
  const [files, setFiles] = useState<File[]>([]);
  const [label, setLabel] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const sample = useMutation({ mutationFn: (s: { profile: string; variant: string }) => api.loadSample(s.profile, s.variant), onSuccess: onLoaded });
  const upload = useMutation({ mutationFn: () => api.upload(files, label || files.map((f) => f.name).join(", ")), onSuccess: onLoaded });
  const add = (list: FileList | null) => list && setFiles((prev) => [...prev, ...Array.from(list).filter((f) => !prev.some((p) => p.name === f.name))]);
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); };

  return (
    <Card title="1 · Choose data" sub="Sample portfolios or your own CSV, Excel or JSON files">
      <Tabs label="Source" value={mode} onChange={setMode} tabs={[{ id: "sample", label: "Sample portfolios" }, { id: "upload", label: "Upload files" }]} />
      {mode === "sample" ? (
        <div className="grid cols-2" style={{ gap: 10 }}>
          {(config?.samples ?? []).map((s) => (
            <button key={`${s.profile}-${s.variant}`} className="list-tile" disabled={sample.isPending}
              onClick={() => sample.mutate(s)}>
              <span className="who-icon" style={{ borderRadius: 10 }}><Database size={16} /></span>
              <span style={{ flex: 1 }}>
                <strong style={{ display: "block", fontWeight: 500 }}>{profileName(s.profile)} · {s.variant}</strong>
                <small className="muted">{s.variant === "clean" ? "Valid synthetic portfolio" : "Same data with injected defects"}</small>
              </span>
              {sample.isPending && sample.variables?.profile === s.profile && sample.variables?.variant === s.variant && <Spinner />}
            </button>
          ))}
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <div className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0}
            onClick={() => input.current?.click()} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
            <Upload size={24} />
            <strong>Drop files here or click to browse</strong>
            <span className="small">One CSV per table (customers, facilities, repayments, delinquency, exposure, transactions, optional sme_indicators and risk_signal_definitions), one Excel workbook, or one JSON file</span>
            <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => add(e.target.files)} />
          </div>
          {files.length > 0 && (
            <div className="row wrap" style={{ gap: 6 }}>
              {files.map((f) => (
                <span key={f.name} className="tag" style={{ gap: 6, alignItems: "center" }}>
                  <FileSpreadsheet size={13} />{f.name}
                  <button className="btn ghost sm" style={{ padding: 0 }} aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x !== f))}><X size={12} /></button>
                </span>
              ))}
            </div>
          )}
          <div className="field">
            <label htmlFor="ds-label">Portfolio name</label>
            <input id="ds-label" className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Retail book October 2026" />
          </div>
          <button className="btn dark" disabled={!files.length || upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? <Spinner /> : <Upload size={16} />}Upload and validate
          </button>
        </div>
      )}
      <div style={{ marginTop: 12 }}><ErrorNote error={sample.error ?? upload.error} /></div>
    </Card>
  );
}

function QualityReport({ dataset }: { dataset: DatasetMeta }) {
  const quality = dataset.quality!;
  const [severity, setSeverity] = useState<string[]>([]);
  const [action, setAction] = useState<string[]>([]);
  const [table, setTable] = useState<string[]>([]);
  const [qTable, setQTable] = useState<string>(Object.keys(quality.quarantined)[0] ?? "");
  const issues = useMemo(() => quality.issues.filter((i: ValidationIssue) =>
    (!severity.length || severity.includes(i.severity)) && (!action.length || action.includes(i.action)) && (!table.length || table.includes(i.table))),
  [quality.issues, severity, action, table]);
  const quarantined = useQuery({
    queryKey: ["quarantined", dataset.dataset_id, qTable], queryFn: () => api.quarantined(dataset.dataset_id, qTable), enabled: !!qTable,
  });
  const qRows = quarantined.data ?? [];
  const qCols = qRows.length ? Object.keys(qRows[0]) : [];

  return (
    <Card title="2 · Validation report" sub={`${dataset.label} · ${dataset.files.length} file(s)`}>
      <div className="kpis">
        <div className="kpi"><div className="stat-label">Rows loaded</div><div className="stat-value mono">{num(Object.values(quality.tables).reduce((a, b) => a + b, 0))}</div><div className="muted tiny">{Object.keys(quality.tables).filter((t) => quality.tables[t] > 0).length} tables</div></div>
        <div className="kpi"><div className="stat-label">Issues found</div><div className="stat-value mono">{quality.issue_count}</div><div className="muted tiny">{quality.severity.error} errors · {quality.severity.warning} warnings</div></div>
        <div className="kpi"><div className="stat-label">Quarantined rows</div><div className="stat-value mono" style={{ color: quality.action.quarantined ? "var(--critical)" : undefined }}>{quality.action.quarantined}</div><div className="muted tiny">set aside, not scored</div></div>
        <div className="kpi"><div className="stat-label">Repaired values</div><div className="stat-value mono" style={{ color: "var(--low)" }}>{quality.action.repaired}</div><div className="muted tiny">derived and recorded</div></div>
      </div>
      {quality.blocking.length > 0 ? (
        <div className="callout error" style={{ marginTop: 14 }}>Cannot score yet: {quality.blocking.map((b) => b.issue).join("; ")}.</div>
      ) : (
        <div className="callout info" style={{ marginTop: 14 }}><CheckCircle2 size={18} color="var(--low)" />
          Ready to score. {quality.has_signal_config ? "This dataset includes signal definitions; its thresholds and weights will be used." : "Default signal definitions will be used."}
        </div>
      )}

      <div className="row wrap" style={{ margin: "16px 0 10px" }}>
        <h4 style={{ fontSize: 14 }}>Issues</h4><span className="spacer" />
        <MultiFilter label="Severity" options={["error", "warning"]} value={severity} onChange={setSeverity} />
        <MultiFilter label="Action" options={["quarantined", "repaired", "kept"]} value={action} onChange={setAction} />
        <MultiFilter label="Table" options={[...new Set(quality.issues.map((i) => i.table))].sort()} value={table} onChange={setTable} />
      </div>
      {issues.length === 0 ? <p className="muted small">No issues{quality.issue_count ? " match these filters" : ""}.</p> : (
        <div className="table-wrap" style={{ maxHeight: 320, border: "1px solid var(--border)", borderRadius: 12 }}>
          <table className="data">
            <thead><tr><th>Record</th><th>Issue</th><th>Severity</th><th>Action</th></tr></thead>
            <tbody>
              {issues.map((i, n) => (
                <tr key={n}>
                  <td className="small" style={{ whiteSpace: "nowrap" }}><span className="mono strong">{i.record_key}</span>
                    <div className="muted tiny">{i.table}{i.field ? ` · ${i.field}` : ""}</div></td>
                  <td className="small">{i.issue}</td>
                  <td><span className={`pill ${i.severity === "error" ? "band-Critical" : "band-Medium"}`}>{i.severity}</span></td>
                  <td><span className={`pill ${i.action === "repaired" ? "lime" : i.action === "quarantined" ? "band-High" : "neutral"}`}>{i.action}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(quality.quarantined).length > 0 && (
        <>
          <h4 style={{ fontSize: 14, margin: "18px 0 10px" }}>Quarantined rows</h4>
          <Tabs label="Quarantined tables" value={qTable} onChange={setQTable}
            tabs={Object.entries(quality.quarantined).map(([t, n]) => ({ id: t, label: `${t} (${n})` }))} />
          {quarantined.isLoading ? <Skeleton height={80} /> : (
            <div className="table-wrap" style={{ maxHeight: 260, border: "1px solid var(--border)", borderRadius: 12 }}>
              <table className="data">
                <thead><tr>{qCols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{qRows.map((row, n) => <tr key={n}>{qCols.map((c) => <td key={c} className="small">{String(row[c] ?? "—")}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function RunPanel({ dataset }: { dataset: DatasetMeta }) {
  const { config, setRunId } = useWorkspace();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(dataset.profile_hint ?? config?.profiles[0]?.id ?? "india");
  const run = useMutation({
    mutationFn: () => api.createRun(dataset.dataset_id, profile),
    onSuccess: (r) => {
      client.setQueryData<RunMeta[]>(["runs"], (old) => [r, ...(old ?? []).filter((x) => x.run_id !== r.run_id)]);
      setRunId(r.run_id);
      client.invalidateQueries({ queryKey: ["runs"] });
      navigate("/");
    },
  });
  const blocked = (dataset.quality?.blocking.length ?? 0) > 0;
  return (
    <Card title="3 · Run assessment" sub="Scores every customer and saves an unchangeable assessment">
      <div className="stack" style={{ gap: 12 }}>
        <div className="field">
          <label htmlFor="profile">Region profile</label>
          <select id="profile" className="input chip-select" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {config?.profiles.map((p) => <option key={p.id} value={p.id}>{profileName(p.id)} ({p.currency})</option>)}
          </select>
          <span className="muted tiny">{config?.profiles.find((p) => p.id === profile)?.description}</span>
        </div>
        <ErrorNote error={run.error} />
        <button className="btn primary block" disabled={blocked || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? <><Spinner />Scoring customers… this takes about 20 seconds</> : <><Play size={16} />Run assessment</>}
        </button>
        <p className="muted tiny">Each run is saved separately, so earlier assessments and analyst decisions stay available in the audit trail.</p>
      </div>
    </Card>
  );
}

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const datasetId = params.get("dataset");
  const client = useQueryClient();
  const recent = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const dataset = useQuery({ queryKey: ["dataset", datasetId], queryFn: () => api.dataset(datasetId!), enabled: !!datasetId });
  const loaded = (d: DatasetMeta) => {
    client.setQueryData(["dataset", d.dataset_id], d);
    client.invalidateQueries({ queryKey: ["datasets"] });
    setParams({ dataset: d.dataset_id });
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Data <b>/ Ingestion & validation</b></h1>
          <p className="hero-sub">Load customer, facility, repayment, delinquency, exposure and transaction data; every record is validated and linked before scoring.</p>
        </div>
      </div>
      <div className="grid cols-main">
        <div className="stack">
          <SourcePicker onLoaded={loaded} />
          {datasetId && (dataset.error ? <ErrorNote error={dataset.error} /> : !dataset.data ? <Skeleton height={240} /> : <QualityReport dataset={dataset.data} />)}
        </div>
        <div className="stack">
          {dataset.data ? <RunPanel dataset={dataset.data} /> : (
            <Card><Empty icon={<Play size={22} />} title="Run an assessment">Choose a sample portfolio or upload files to see the validation report and score it.</Empty></Card>
          )}
          <Card title="Recent datasets" sub="Stored by content fingerprint">
            <div className="stack" style={{ gap: 8 }}>
              {(recent.data ?? []).slice(0, 8).map((d) => (
                <button key={d.dataset_id} className={`list-tile${d.dataset_id === datasetId ? " selected" : ""}`} onClick={() => setParams({ dataset: d.dataset_id })}>
                  <span className="radio" />
                  <span style={{ minWidth: 0 }}><strong style={{ display: "block", fontWeight: 500 }}>{d.label}</strong>
                    <small className="muted">{d.origin} · {d.files.length} files · {date(d.created_at, true)}</small></span>
                </button>
              ))}
              {recent.data?.length === 0 && <p className="muted small">Nothing loaded yet.</p>}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
