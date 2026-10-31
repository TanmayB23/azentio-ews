import { useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight, ChevronsUpDown, Database, FileText, HelpCircle, History, LayoutDashboard, ListChecks, Network, Search, Settings,
} from "lucide-react";
import { api } from "../api";
import { date, initials, profileName } from "../format";
import { useWorkspace } from "../state";

const PAGES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Overview", sub: "Portfolio risk at a glance" },
  "/watchlist": { title: "Watchlist", sub: "Customers that need monitoring or intervention" },
  "/customers": { title: "Customer", sub: "Risk assessment, evidence and analyst review" },
  "/portfolio": { title: "Portfolio & clusters", sub: "Concentrations of emerging risk" },
  "/data": { title: "Data & validation", sub: "Load portfolios, check quality and run assessments" },
  "/audit": { title: "Audit trail", sub: "Saved assessments and every analyst decision" },
  "/memo": { title: "Risk memo", sub: "Management summary of this assessment" },
  "/settings": { title: "Settings", sub: "Your analyst profile" },
  "/help": { title: "How scoring works", sub: "Signals, bands, modifiers and decisions" },
};

export function Logo() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden>
      <circle cx="16" cy="16" r="16" fill="#0f3d2e" />
      <path d="M9 18.5c4.5-1 8.5-4.4 10.6-9.5 1.9 4.4.8 9.8-3.3 12.6-2.6 1.8-5.4 1.8-7.3-3.1z" fill="#a3e77f" />
      <path d="M11.5 22.5c2.5-3.5 5.2-6.3 8.2-8.4" stroke="#0f3d2e" strokeWidth="1.4" fill="none" strokeLinecap="round" />
    </svg>
  );
}

function RunSwitcher() {
  const { runs, run, setRunId } = useWorkspace();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="switcher" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        disabled={!runs.length} title="Switch assessment">
        <span className="switcher-dot">{run ? profileName(run.profile).slice(0, 2).toUpperCase() : "—"}</span>
        <span className="switcher-text">
          <strong>{run ? run.dataset_label : "No assessment yet"}</strong>
          <small>{run ? `${profileName(run.profile)} · ${date(run.created_at)}` : "Load data to begin"}</small>
        </span>
        <ChevronsUpDown size={16} className="faint" />
      </button>
      {open && (
        <div className="popover" role="listbox" aria-label="Assessments" style={{ width: "100%" }}>
          {runs.map((r) => (
            <button key={r.run_id} role="option" aria-selected={r.run_id === run?.run_id}
              className={`list-tile${r.run_id === run?.run_id ? " selected" : ""}`} style={{ marginBottom: 4 }}
              onClick={() => { setRunId(r.run_id); setOpen(false); }}>
              <span className="radio" />
              <span style={{ minWidth: 0 }}>
                <strong style={{ display: "block", fontWeight: 500 }}>{r.dataset_label}</strong>
                <small className="muted">{profileName(r.profile)} · {r.customer_count} customers · {date(r.created_at, true)}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Sidebar() {
  const { run } = useWorkspace();
  const summary = useQuery({ queryKey: ["summary", run?.run_id], queryFn: () => api.summary(run!.run_id), enabled: !!run });
  const pending = summary.data ? summary.data.reviews.elevated - summary.data.reviews.reviewed : 0;
  const nav = [
    { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/watchlist", label: "Watchlist", icon: ListChecks, count: pending },
    { to: "/portfolio", label: "Portfolio & clusters", icon: Network },
    { to: "/memo", label: "Risk memo", icon: FileText },
    { to: "/data", label: "Data & validation", icon: Database },
    { to: "/audit", label: "Audit trail", icon: History },
  ];
  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand"><Logo /><span className="brand-name">EWS<span>.</span></span></div>
      <RunSwitcher />
      <nav>
        <div className="nav-label">Main menu</div>
        <div className="nav">
          {nav.map(({ to, label, icon: Icon, end, count }) => (
            <NavLink key={to} to={to} end={end}>
              <Icon size={18} strokeWidth={1.8} />{label}
              {!!count && count > 0 && <span className="count" title={`${count} High/Critical not yet reviewed`}>{count}</span>}
            </NavLink>
          ))}
        </div>
      </nav>
      <nav>
        <div className="nav-label">Preference</div>
        <div className="nav">
          <NavLink to="/settings"><Settings size={18} strokeWidth={1.8} />Settings</NavLink>
          <NavLink to="/help"><HelpCircle size={18} strokeWidth={1.8} />How scoring works</NavLink>
        </div>
      </nav>
      <div className="side-card">
        <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden>
          <rect x="6" y="12" width="28" height="20" rx="5" fill="#edf9e5" stroke="#0f3d2e" strokeWidth="1.6" />
          <path d="M13 23l5 4 9-9" stroke="#0f3d2e" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="31" cy="11" r="5" fill="#a3e77f" />
        </svg>
        <h4>Fresh data in?</h4>
        <p>Upload the latest portfolio extract and re-score. Earlier assessments stay saved for audit.</p>
        <NavLink to="/data" className="btn dark block">New assessment <ArrowUpRight size={16} /></NavLink>
      </div>
    </aside>
  );
}

function Topbar() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { analyst } = useWorkspace();
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const page = PAGES["/" + (pathname.split("/")[1] ?? "")] ?? PAGES["/"];
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault(); input.current?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  const submit = (e: FormEvent) => { e.preventDefault(); navigate(`/watchlist?q=${encodeURIComponent(q.trim())}`); };
  return (
    <header className="topbar">
      <div className="topbar-title"><strong>{page.title}</strong><small>{page.sub}</small></div>
      <div className="topbar-spacer" />
      <form className="search" role="search" onSubmit={submit}>
        <Search size={16} aria-hidden />
        <label htmlFor="global-search" className="sr-only">Search customers</label>
        <input id="global-search" ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customer name or ID" />
        <span className="kbd" aria-hidden>/</span>
      </form>
      <NavLink to="/help" className="icon-btn" aria-label="How scoring works"><HelpCircle size={19} /></NavLink>
      <NavLink to="/settings" className="icon-btn" aria-label="Settings"><Settings size={19} /></NavLink>
      <NavLink to="/settings" className="avatar" title={analyst || "Set your analyst name"}>{analyst ? initials(analyst) : "?"}</NavLink>
    </header>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    <div className="shell">
      <Sidebar />
      <div className="main">
        <Topbar />
        <main className="page" key={pathname}><Outlet /></main>
      </div>
    </div>
  );
}
