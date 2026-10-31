import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { api } from "../api";
import { Card, Empty, ReviewPill, Skeleton } from "../components/ui";
import { date, profileName } from "../format";
import { useWorkspace } from "../state";

export function Audit() {
  const { runs, run, setRunId } = useWorkspace();
  const log = useQuery({ queryKey: ["reviewLog", run?.run_id], queryFn: () => api.reviewLog(run!.run_id), enabled: !!run });
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="crumbs">Audit <b>/ Assessments & decisions</b></h1>
          <p className="hero-sub">Every assessment and analyst decision is append-only: nothing here can be edited or deleted.</p>
        </div>
      </div>
      <div className="grid cols-main">
        <Card className="flush">
          <div className="card-head" style={{ padding: "18px 18px 0" }}><div><h3>Decision log</h3><p className="sub">{run ? run.dataset_label : "No assessment selected"}</p></div></div>
          {!run ? <Empty icon={<History size={22} />} title="No assessments yet" /> : !log.data ? <div style={{ padding: 18 }}><Skeleton height={120} /></div>
            : log.data.length === 0 ? <Empty title="No decisions recorded">Open a customer from the watchlist and record a review.</Empty> : (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>When</th><th>Customer</th><th>Decision</th><th>Reason</th><th>Analyst</th></tr></thead>
                  <tbody>
                    {log.data.map((r) => (
                      <tr key={r.review_id}>
                        <td className="small">{date(r.created_at, true)}</td>
                        <td><Link to={`/customers/${r.customer_id}`} className="strong">{r.customer_id}</Link></td>
                        <td><ReviewPill decision={r.decision} /></td>
                        <td className="small" style={{ maxWidth: 380 }}>{r.reason}</td>
                        <td className="small">{r.analyst}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
        <Card title="Saved assessments" sub="Select one to make it active across the app">
          <div className="stack" style={{ gap: 8 }}>
            {runs.map((r) => (
              <button key={r.run_id} className={`list-tile${r.run_id === run?.run_id ? " selected" : ""}`} onClick={() => setRunId(r.run_id)}>
                <span className="radio" />
                <span style={{ minWidth: 0, flex: 1 }}><strong style={{ display: "block", fontWeight: 500 }}>{r.dataset_label}</strong>
                  <small className="muted">{profileName(r.profile)} · {r.customer_count} customers · {date(r.created_at, true)}</small></span>
                <span className="tag">{r.run_id.slice(0, 8)}</span>
              </button>
            ))}
            {runs.length === 0 && <p className="muted small">No assessments yet.</p>}
          </div>
        </Card>
      </div>
    </>
  );
}
