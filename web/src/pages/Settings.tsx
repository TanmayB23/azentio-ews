import { useState, type FormEvent } from "react";
import { Card, Toast } from "../components/ui";
import { useWorkspace } from "../state";

export function SettingsPage() {
  const { analyst, setAnalyst } = useWorkspace();
  const [name, setName] = useState(analyst);
  const [toast, setToast] = useState<string | null>(null);
  const save = (e: FormEvent) => { e.preventDefault(); setAnalyst(name.trim()); setToast("Saved"); };
  return (
    <>
      <div className="page-head"><div><h1 className="crumbs">Settings <b>/ Analyst profile</b></h1></div></div>
      <Card title="Analyst profile" sub="Your name is recorded on every review decision you make" className="" >
        <form onSubmit={save} className="stack" style={{ gap: 12, maxWidth: 420 }}>
          <div className="field">
            <label htmlFor="analyst-name">Analyst name</label>
            <input id="analyst-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Priya Nair" />
          </div>
          <button className="btn primary" disabled={!name.trim()}>Save</button>
          <p className="muted tiny">Stored in this browser only. Single sign-on and role-based access can replace this in production.</p>
        </form>
      </Card>
      <Toast message={toast} onDone={() => setToast(null)} />
    </>
  );
}
