"""Plain-English summaries built only from computed signal results."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ews.contracts import CustomerResult, SignalResult
    from ews.engine.views import CustomerViews

PHRASES = {
    "late_instalments_in_window": "{v:.0f} late instalment month(s) in the last 6",
    "slope_of_dpd_per_month": "days past due rising {v:.1f} days/month",
    "partially_paid_instalments_in_window": "{v:.0f} partial payment(s)",
    "current_dpd": "currently {v:.0f} days past due",
    "consecutive_months_total_inflows_declining": "inflows down {v:.0f} consecutive months",
    "pct_change_avg_inflow_last3m_vs_prior3m": "average inflows {v:+.0f}% (last 3m vs prior 3m)",
    "pct_change_avg_balance_last3m_vs_prior3m": "average balance {v:+.0f}%",
    "months_outflow_gt_inflow": "outflows exceeded inflows in {v:.0f} month(s)",
    "bounced_txns_in_window": "{v:.0f} bounced transaction(s)",
    "utilisation_pct_change_in_points": "utilisation {v:+.0f} pts",
    "new_facilities_in_window": "{v:.0f} new facility(ies) in 6 months",
    "change_in_obligation_to_inflow_pct_points": "obligations-to-inflow ratio {v:+.0f} pts",
    "new_credit_inquiries_90d_latest": "{v:.0f} credit inquiries in 90 days",
    "tax_filings_late_or_missed_in_window": "{v:.0f} tax return(s) filed late or missed",
    "receivable_days_change_in_window": "receivable days {v:+.0f}",
}


def phrase(s: SignalResult, metrics: dict[str, str]) -> str:
    template = PHRASES.get(metrics.get(s.signal_id, ""))
    if template is None or s.value is None:
        return s.name
    return template.format(v=s.value)


def summarise(result: CustomerResult, v: CustomerViews, defs: dict) -> str:
    if result.status == "Insufficient data":
        n_rep = len(v.repay_months)
        n_txn = len(v.transactions)
        return (f"Insufficient data: {n_rep} month(s) of repayment history and {n_txn} month(s) of transactions "
                f"(confidence {result.confidence:.0%}). Risk is not inferred from missing information.")
    active = sorted((s for s in result.signals if s.points > 0), key=lambda s: s.points, reverse=True)
    metrics = {d["signal_id"]: str(d["metric"]).split()[0] for d in defs["signals"]}
    parts = [phrase(s, metrics) for s in active[:3]]
    text = "; ".join(parts) if parts else "No active warning signals"
    text = text[0].upper() + text[1:]
    notes = [m.split(":")[0] for m in result.modifiers if not m.endswith("signal weight has enough data")]
    if notes:
        text += ". " + "; ".join(notes)
    return text + "."
