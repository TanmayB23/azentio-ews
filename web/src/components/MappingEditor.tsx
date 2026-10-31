import { AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import type { FileMap, MappingProposal } from "../types";

const TABLES = ["customers", "facilities", "repayments", "delinquency", "exposure", "transactions", "sme_indicators"];

/** Review and edit a proposed file-to-table and column-to-column mapping before upload. */
export function MappingEditor({ proposal, value, onChange }: {
  proposal: MappingProposal; value: FileMap[]; onChange: (files: FileMap[]) => void;
}) {
  const setTable = (i: number, table: string) =>
    onChange(value.map((f, j) => (j === i ? { ...f, table, columns: f.columns.map((c) => ({ ...c, target: "" })) } : f)));
  const setTarget = (i: number, source: string, target: string) =>
    onChange(value.map((f, j) => (j !== i ? f : {
      ...f, columns: f.columns.map((c) => (c.source === source ? { ...c, target } : c.target === target && target ? { ...c, target: "" } : c)),
    })));

  // required columns still missing after the analyst's edits
  const missing: Record<string, string[]> = {};
  for (const f of value) {
    if (f.table === "ignore") continue;
    const have = new Set(f.columns.map((c) => c.target || (proposal.targets[f.table]?.includes(c.source) ? c.source : "")));
    const required = proposal.missing_required[f.table] ?? [];
    const stillMissing = required.filter((r) => !have.has(r));
    if (stillMissing.length) missing[f.table] = stillMissing;
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="callout info small">
        <Sparkles size={16} color="var(--forest)" />
        <span>Proposed by {proposal.source === "fuzzy" ? "name matching (no AI key)" : `AI · ${proposal.model}`}.
          Only file names, column headers and three sample values per column were used. Check each row, then upload.
          {proposal.error && <> AI unavailable ({proposal.error}).</>}</span>
      </div>
      {value.map((f, i) => (
        <div key={f.file} className="kpi" style={{ background: "var(--surface)" }}>
          <div className="row wrap" style={{ marginBottom: 8 }}>
            <strong>{f.file}</strong><span className="muted small">→</span>
            <select className="chip-select" value={f.table} onChange={(e) => setTable(i, e.target.value)} aria-label={`Table for ${f.file}`}>
              {[...TABLES, "ignore"].map((t) => <option key={t} value={t}>{t === "ignore" ? "Ignore this file" : t}</option>)}
            </select>
          </div>
          {f.table !== "ignore" && (
            <div className="table-wrap" style={{ maxHeight: 240 }}>
              <table className="data">
                <thead><tr><th>Your column</th><th>Maps to</th></tr></thead>
                <tbody>
                  {f.columns.map((c) => {
                    const alreadyOurs = !c.target && proposal.targets[f.table]?.includes(c.source);
                    return (
                      <tr key={c.source}>
                        <td className="small mono">{c.source}</td>
                        <td>
                          {alreadyOurs ? <span className="pill lime small">already {c.source}</span> : (
                            <select className="chip-select" value={c.target} onChange={(e) => setTarget(i, c.source, e.target.value)}
                              aria-label={`Target for ${c.source}`}>
                              <option value="">(keep as is)</option>
                              {(proposal.targets[f.table] ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
                            </select>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {Object.keys(missing).length > 0 ? (
        <div className="callout warn small"><AlertTriangle size={16} />
          Still missing required columns: {Object.entries(missing).map(([t, cols]) => `${t}: ${cols.join(", ")}`).join(" · ")}</div>
      ) : (
        <div className="callout info small"><CheckCircle2 size={16} color="var(--low)" />All required columns are mapped.</div>
      )}
      {proposal.tables_not_supplied.length > 0 && (
        <p className="muted tiny">No file maps to: {proposal.tables_not_supplied.join(", ")}.</p>
      )}
    </div>
  );
}
