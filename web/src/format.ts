const CURRENCY_LOCALE: Record<string, string> = { INR: "en-IN", AED: "en-AE" };

export function money(value: number | null | undefined, currency = "INR", compact = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(CURRENCY_LOCALE[currency] ?? "en-US", {
    style: "currency", currency, notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 0,
  }).format(value);
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

export const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? "—" : `${num(value * 100, digits)}%`;

export function date(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 7 ? `${iso}-01` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", withTime
    ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "short", year: "numeric" });
}

export function monthLabel(month: string): string {
  const d = new Date(`${month}-01`);
  return Number.isNaN(d.getTime()) ? month : d.toLocaleString("en-GB", { month: "short", year: "2-digit" });
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");

/** What a cluster's multiplier measures, in words: "Receivable days rising: 12 of 15 vs 7% of the book". */
export function clusterBasis(c: { basis: string; basis_hits: number; n_customers: number; portfolio_rate: number }): string {
  const signal = c.basis.match(/\((.+)\)/)?.[1];
  const what = signal ?? "Medium or above";
  const rate = c.portfolio_rate * 100;
  return `${what}: ${c.basis_hits} of ${c.n_customers} vs ${rate < 10 ? rate.toFixed(1) : Math.round(rate)}% of the book`;
}

export const profileName = (id: string) => (id === "gcc_islamic" ? "GCC · Islamic" : id === "india" ? "India" : id);
export const profileCurrency = (id: string) => (id === "gcc_islamic" ? "AED" : "INR");
