import { BAND_HEX, Card } from "../components/ui";
import type { Band } from "../types";

const BANDS: [Band, string, string][] = [
  ["Low", "0–24", "Routine monitoring"],
  ["Medium", "25–49", "Watch: review at next cycle"],
  ["High", "50–74", "Investigate: contact customer or RM"],
  ["Critical", "75–100", "Escalate: credit committee / collections"],
  ["Insufficient data", "—", "Collect data; risk is never inferred from missing information"],
];

export function Help() {
  return (
    <>
      <div className="page-head"><div><h1 className="crumbs">Help <b>/ How the Early Warning Score works</b></h1>
        <p className="hero-sub">A score from 0 to 100 where a higher score means higher credit risk. Every point can be traced to a signal.</p></div></div>
      <div className="grid cols-2">
        <Card title="1 · Signals" sub="15 configurable indicators, each with a trigger and a saturation level">
          <p className="small">Each signal measures a change over the last months, not a single data point: late-payment frequency, rising days past due, partial payments, current delinquency, falling income, balance erosion, outflows above inflows, bounced payments, rising utilisation, new facilities, obligations growing faster than income, credit inquiries, and for SMEs tax-filing delays and rising receivable days.</p>
          <p className="small" style={{ marginTop: 8 }}>A signal's strength rises from 0 at its trigger to 1 at its saturation. Signals without enough data are marked <b>missing data</b>; signals that do not fit the customer are <b>not applicable</b>.</p>
        </Card>
        <Card title="2 · Score" sub="Four risk areas combined">
          <p className="small">Signals are grouped into Repayment, Cash flow, Exposure and Business. Each area scores 0–100. The final score takes the highest area in full and adds 35%, 15% and 10% of the next three, so one severe problem is enough to reach High and problems in several areas push towards Critical.</p>
          <p className="small" style={{ marginTop: 8 }}>Confidence shows how much of the applicable signal weight could be evaluated.</p>
        </Card>
        <Card title="3 · Adjustments" sub="Context that changes the score, always listed on the customer page">
          <ul className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
            <li><b>Temporary missed payment:</b> one isolated late payment, clean before and recovered after, counts at 25% with supporting evidence or 60% without.</li>
            <li><b>Seasonality:</b> an income dip that matches the same months last year counts at 30%.</li>
            <li><b>Holidays:</b> a short delay on a weekend or bank holiday is treated as an exception.</li>
            <li><b>Roll-forward risk:</b> rising delays ending in an unpaid instalment raise the score to at least 75.</li>
            <li><b>Recent delinquency episode:</b> repeated delays of 10+ days raise the score to at least 25.</li>
          </ul>
        </Card>
        <Card title="4 · Bands and monitoring" sub="What each band means for action">
          <div className="stack" style={{ gap: 8 }}>
            {BANDS.map(([b, range, action]) => (
              <div key={b} className="row small"><span className="legend-swatch" style={{ background: BAND_HEX[b] }} /><b style={{ width: 120 }}>{b}</b><span className="muted mono" style={{ width: 60 }}>{range}</span><span>{action}</span></div>
            ))}
          </div>
        </Card>
        <Card title="5 · Analyst decisions" sub="Recorded against the saved alert">
          <p className="small">Continue Monitoring · Requires Investigation · False Positive · Escalate for Review. A reason is required. Decisions are appended to a history: the original score and evidence are never changed, and the database rejects edits and deletions.</p>
        </Card>
        <Card title="Unusual behaviour (machine learning)" sub="An isolation forest, signal UB01">
          <p className="small">Rules catch the patterns we anticipated. To catch combinations nobody wrote a rule for, an isolation forest learns what typical behaviour looks like across comparable customers (individuals and SMEs separately) from 14 measures of the last six months: income trend and volatility, income versus the same months last year, balances, outflows, bounced payments, utilisation, obligations, inquiries, late months, days past due and, for SMEs, receivable days and tax filings.</p>
          <p className="small" style={{ marginTop: 8 }}>A customer more unusual than 95% of comparable customers gets the signal, at full strength above 99.5%. It adds at most 8 points on top of the score, lists the measures furthest from typical, and is reduced when a documented one-off explains it. Missing data is filled with typical values, so it never looks unusual, and the signal does not affect data confidence.</p>
        </Card>
        <Card title="6 · Clusters" sub="Portfolio concentrations">
          <p className="small">Customers are grouped by industry, region, product, segment and portfolio. A group is flagged when its share of elevated customers, or of customers sharing the same warning signal, is significantly above the portfolio rate. Broad groups that only echo a stronger cluster inside them are not reported.</p>
        </Card>
      </div>
    </>
  );
}
