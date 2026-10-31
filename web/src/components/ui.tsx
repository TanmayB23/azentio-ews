import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, Inbox } from "lucide-react";
import clsx from "clsx";
import type { Band } from "../types";

export const BAND_COLOR: Record<Band, string> = {
  Critical: "var(--critical)", High: "var(--high)", Medium: "var(--medium)", Low: "var(--low)",
  "Insufficient data": "var(--insufficient)",
};
export const BAND_HEX: Record<Band, string> = {
  Critical: "#d43f3a", High: "#e2711d", Medium: "#c99512", Low: "#86d95c", "Insufficient data": "#b8c2cd",
};
const bandClass = (band: string) => `band-${band.split(" ")[0]}`;

export function BandPill({ band }: { band: Band | string | null }) {
  const b = band ?? "Insufficient data";
  return <span className={clsx("pill", bandClass(b))}><span className="dot" aria-hidden />{b}</span>;
}

export function ReviewPill({ decision }: { decision: string | null }) {
  if (!decision) return <span className="pill neutral">Not reviewed</span>;
  const tone = decision === "False Positive" ? "lime" : decision === "Escalate for Review" ? "band-Critical"
    : decision === "Requires Investigation" ? "band-High" : "neutral";
  return <span className={clsx("pill", tone)}>{decision}</span>;
}

export function Card({ title, sub, end, children, className, id }: {
  title?: ReactNode; sub?: ReactNode; end?: ReactNode; children: ReactNode; className?: string; id?: string;
}) {
  return (
    <section className={clsx("card", className)} aria-labelledby={id}>
      {(title || end) && (
        <header className="card-head">
          <div>
            {title && <h3 id={id}>{title}</h3>}
            {sub && <p className="sub">{sub}</p>}
          </div>
          {end && <div className="end">{end}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon ?? <Inbox size={24} />}</div>
      <h3>{title}</h3>
      {children && <p style={{ maxWidth: 420 }}>{children}</p>}
      {action}
    </div>
  );
}

export const Spinner = ({ label }: { label?: string }) => (
  <span className="row" role="status"><span className="spinner" aria-hidden />{label && <span className="muted">{label}</span>}</span>
);

export const Skeleton = ({ height = 16, width = "100%" }: { height?: number; width?: number | string }) => (
  <div className="skeleton" style={{ height, width }} aria-hidden />
);

export function ScoreBar({ score, band }: { score: number | null; band: Band }) {
  if (score === null) return <span className="muted small">Not scored</span>;
  return (
    <div className="scorebar">
      <span className="strong mono" style={{ width: 30 }}>{Math.round(score)}</span>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${score}%`, background: BAND_COLOR[band] }} /></div>
    </div>
  );
}

export function ScoreRing({ score, band, size = 132 }: { score: number | null; band: Band | null; size?: number }) {
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  const value = score ?? 0;
  const color = band ? BAND_HEX[band] : BAND_HEX["Insufficient data"];
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={score === null ? "Not scored: insufficient data" : `Risk score ${Math.round(value)} of 100, ${band}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1ea" strokeWidth={12} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={12} strokeLinecap="round"
        strokeDasharray={`${(value / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="47%" textAnchor="middle" fontSize={size / 4.2} fontWeight={600} fill="#13211b">
        {score === null ? "—" : Math.round(value)}
      </text>
      <text x="50%" y="66%" textAnchor="middle" fontSize={11} fill="#76807a">of 100 risk</text>
    </svg>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: {
  tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void; label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}>{t.label}</button>
      ))}
    </div>
  );
}

export function MultiFilter({ label, options, value, onChange }: {
  label: string; options: string[]; value: string[]; onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);
  const toggle = (opt: string) => onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className={clsx("filter-btn", value.length > 0 && "active")} aria-haspopup="true" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        {label}{value.length > 0 && <span className="strong">· {value.length}</span>}<ChevronDown size={14} />
      </button>
      {open && (
        <div className="popover" role="group" aria-label={`${label} filter`}>
          {options.length === 0 && <p className="muted small" style={{ padding: 8 }}>No options</p>}
          {options.map((opt) => (
            <label key={opt}>
              <input type="checkbox" checked={value.includes(opt)} onChange={() => toggle(opt)} />{opt}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [message, onDone]);
  if (!message) return null;
  return <div className="toast" role="status"><Check size={18} />{message}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="callout error" role="alert">{error instanceof Error ? error.message : String(error)}</div>;
}
