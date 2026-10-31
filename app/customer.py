"""Customer dashboard cards built from scored evidence and source observations."""
from html import escape
import math

import pandas as pd
import streamlit as st

from app.ui import BAND_COLORS
from app.views import customer_table, monthly_chart


def text(value):
    return escape(str(value))


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def amount(value, compact=False):
    value = number(value)
    if value is None:
        return "Not available"
    if compact and abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    if compact and abs(value) >= 1_000:
        return f"{value / 1_000:,.1f}K"
    return f"{value:,.0f}"


def measurement(value):
    value = number(value)
    return "--" if value is None else f"{value:,.2f}".rstrip("0").rstrip(".")


def latest(frame, as_of):
    if frame.empty or "month" not in frame:
        return pd.Series(dtype=object)
    dated = frame.assign(_date=pd.to_datetime(frame.month, format="mixed", errors="coerce"))
    dated = dated.loc[dated._date <= pd.Timestamp(as_of)].sort_values("_date")
    return dated.iloc[-1] if not dated.empty else pd.Series(dtype=object)


def chip(label):
    bg, fg = BAND_COLORS.get(label, ("#edf2fa", "#3d5477"))
    return f'<span class="cd-chip" style="background:{bg};color:{fg}">{text(label)}</span>'


def card(title, content, extra=""):
    return f'<section class="cd-card {extra}"><h3>{text(title)}</h3>{content}</section>'


def gauge(score, band):
    cx, cy, radius = 120, 104, 78
    def point(angle):
        radians = math.radians(angle)
        return cx + radius * math.cos(radians), cy + radius * math.sin(radians)
    def arc(start, end):
        x1, y1 = point(start)
        x2, y2 = point(end)
        return f'M {x1:.2f} {y1:.2f} A {radius} {radius} 0 0 1 {x2:.2f} {y2:.2f}'
    score = number(score)
    segments = []
    for i, color in enumerate(("#159967", "#ecc044", "#f39a35", "#e65c62")):
        segments.append(f'<path d="{arc(150+i*60, 150+(i+1)*60)}" stroke="{color if score is not None else "#dce4ee"}"/>')
    marker = ""
    if score is not None:
        x, y = point(150 + min(100, max(0, score))*2.4)
        marker = f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="white" stroke="#132c50" stroke-width="3"/>'
    value = "--" if score is None else f"{score:.1f}".removesuffix(".0")
    label = "Not scored" if score is None else "out of 100"
    return f'<svg class="cd-gauge" viewBox="0 0 240 172" role="img" aria-label="{text(label if score is None else f"Risk score {value} out of 100; higher is riskier")}"><g fill="none" stroke-width="17" stroke-linecap="butt">{"".join(segments)}</g>{marker}<text x="120" y="100" text-anchor="middle" class="cd-gauge-value">{value}</text><text x="120" y="123" text-anchor="middle" class="cd-gauge-label">{label}</text><text x="28" y="163" class="cd-gauge-label">Low</text><text x="176" y="163" class="cd-gauge-label">Critical</text></svg>'


def sparkline(series, color, label):
    values = [number(value) for value in series]
    usable = [value for value in values if value is not None]
    if len(usable) < 2:
        return '<span class="cd-spark-empty">Trend unavailable</span>'
    low, high = min(usable), max(usable)
    span = high-low or 1
    paths, current = [], []
    for index, value in enumerate(values):
        if value is None:
            if current:
                paths.append(current)
                current = []
            continue
        current.append((8 + 144*index/max(len(values)-1, 1), 48-36*(value-low)/span))
    if current:
        paths.append(current)
    lines = ''.join('<polyline points="'+' '.join(f'{x:.1f},{y:.1f}' for x,y in points)+'"/>' for points in paths)
    return f'<svg class="cd-spark" viewBox="0 0 160 60" role="img" aria-label="{text(label)}"><g fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round">{lines}</g></svg>'


def render_customer_dashboard(ds, result, row):
    cid = result.customer_id
    customer = customer_table(ds, "customers", cid)
    info = customer.iloc[0] if not customer.empty else pd.Series(dtype=object)
    facilities = customer_table(ds, "facilities", cid)
    exposure = customer_table(ds, "exposure", cid)
    transactions = customer_table(ds, "transactions", cid)
    for name, frame in (("exposure", exposure), ("transactions", transactions)):
        if "month" in frame:
            mask = pd.to_datetime(frame.month, format="mixed", errors="coerce") <= pd.Timestamp(result.as_of)
            if name == "exposure":
                exposure = frame.loc[mask]
            else:
                transactions = frame.loc[mask]
    exp = latest(exposure, result.as_of)
    tx = latest(transactions, result.as_of)
    name = info.get("customer_name", cid)
    manager = info.get("relationship_manager", "Not assigned")
    initials = ''.join(part[0] for part in str(manager).split()[:2]) or "--"
    sanctioned = pd.to_numeric(facilities.get("sanctioned_amount", pd.Series(dtype=float)), errors="coerce").sum(min_count=1)
    profile = card("Borrower profile",
        f'<div class="cd-identity"><div class="cd-building" aria-hidden="true">&#9638;</div><div><h4>{text(name)}</h4><span class="cd-muted">{text(cid)} &middot; {text(info.get("customer_type", "Customer"))}</span></div></div>'
        f'<div class="cd-profile-grid"><div><label>Industry</label><strong>{text(info.get("industry", "Not available"))}</strong></div><div><label>Relationship manager</label><strong><span class="cd-avatar">{text(initials)}</span>{text(manager)}</strong></div><div><label>Region</label><strong>{text(info.get("region", "Not available"))}</strong></div><div><label>Segment</label><strong>{text(info.get("segment", "Not available"))}</strong></div></div>'
        f'<div class="cd-pair cd-divider"><div><label>Total outstanding</label><b>{amount(row.get("total_outstanding"), True)}</b></div><div><label>Total sanctioned</label><b>{amount(sanctioned, True)}</b></div></div>')
    risk = card("Credit risk assessment", f'<div class="cd-assessment">{gauge(result.score, result.band)}<div class="cd-risk-meta">{chip(result.band or result.status)}<label>Confidence</label><strong>{result.confidence:.0%}</strong><span class="cd-muted">Higher score = higher risk</span></div></div>'
        f'<div class="cd-pair cd-divider"><div><label>Monitoring status</label><strong>{text(result.monitoring_status)}</strong></div><div><label>Assessment date</label><strong>{text(result.as_of)}</strong></div></div>')
    inflows, outflows = number(tx.get("total_inflows")), number(tx.get("total_outflows"))
    net = inflows-outflows if inflows is not None and outflows is not None else None
    month = pd.Timestamp(tx["_date"]).strftime("%b %Y") if "_date" in tx else "No observations"
    financial_rows = ''.join(f'<tr><td>{label}</td><td>{amount(value)}</td></tr>' for label, value in (("Total inflows", inflows), ("Total outflows", outflows), ("Net cash flow", net), ("Average balance", tx.get("avg_balance"))))
    financial = card("Financial snapshot", f'<div class="cd-document"><span class="cd-file" aria-hidden="true">&#9776;</span><div><strong>Monthly account activity</strong><span class="cd-muted">{text(month)}</span></div><span class="cd-source">Source data</span></div><table class="cd-table"><thead><tr><th>Metric</th><th>Amount</th></tr></thead><tbody>{financial_rows}</tbody></table><p class="cd-footnote">Amounts in source currency.</p>')
    active = sorted((signal for signal in result.signals if signal.applicable and signal.evaluated and signal.strength > 0), key=lambda signal: signal.points, reverse=True)
    monitored = active[:4] or [signal for signal in result.signals if signal.applicable][:4]
    signal_table = ''.join(f'<tr><td><strong>{text(signal.signal_id)}</strong><span class="cd-muted cd-signal-name">{text(signal.name)}</span></td><td>{measurement(signal.value)}</td><td>{"Active" if signal.evaluated and signal.strength > 0 else "Clear" if signal.evaluated else "Missing data"}</td></tr>' for signal in monitored)
    monitoring = card("Signal monitoring", f'<table class="cd-table cd-monitoring"><thead><tr><th>Indicator</th><th>Value</th><th>Status</th></tr></thead><tbody>{signal_table}</tbody></table><p class="cd-footnote">Thresholds, saturation and evidence are in Risk evidence below.</p>')
    pillar_colors = {"Repayment": "#2b67dd", "Cash flow": "#33a482", "Exposure": "#efa642", "Business": "#8e78cc"}
    pillar_rows = ''.join(f'<div class="cd-pillar"><div><span>{text(pillar)}</span><strong>{value:.1f}<small> / 100</small></strong></div><div class="cd-track"><span style="width:{min(100,max(0,value)):.1f}%;background:{pillar_colors.get(pillar,"#2b67dd")}"></span></div></div>' for pillar, value in result.pillar_scores.items())
    if not pillar_rows:
        pillar_rows = '<p class="cd-muted">Not enough data to assess any risk pillar.</p>'
    pillars = card("Risk pillars", pillar_rows+f'<div class="cd-coverage"><span>Data confidence</span><strong>{result.confidence:.0%}</strong></div><p class="cd-footnote">Pillars with sufficient data are shown.</p>')
    alerts = []
    if result.status == "Insufficient data":
        alerts.append(f'<div class="cd-alert"><span class="cd-alert-icon">i</span><div><strong>Collect more data</strong><p>{text(result.summary)}</p></div></div>')
    else:
        for signal in active[:3]:
            alerts.append(f'<div class="cd-alert"><span class="cd-alert-icon">!</span><div><strong>{text(signal.name)}</strong><p>{text(signal.signal_id)} &middot; {signal.points:.2f} points &middot; {signal.strength:.0%} strength</p></div></div>')
        if not alerts:
            alerts.append('<p class="cd-muted">No active warning signals in this assessment.</p>')
    alert_card = card("Customer alerts", ''.join(alerts)+f'<div class="cd-alert-footer">{len(active)} active signals &middot; {len(result.modifiers)} rule notes</div>')
    exp_chart = monthly_chart(exposure, "month", ["total_outstanding"], worst=True)
    tx_chart = monthly_chart(transactions, "month", ["total_inflows", "total_outflows"])
    util_chart = monthly_chart(exposure, "month", ["utilisation_pct"], worst=True)
    outstanding_trend = exp_chart.total_outstanding if not exp_chart.empty else []
    net_trend = tx_chart.total_inflows-tx_chart.total_outflows if not tx_chart.empty else []
    util_trend = util_chart.utilisation_pct if not util_chart.empty else []
    util = number(exp.get("utilisation_pct"))
    tiles = []
    for label, value, series, color, caption in (
        ("Total outstanding", amount(row.get("total_outstanding"), True), outstanding_trend, "#2869e8", "Monthly exposure history"),
        ("Net cash flow", amount(net, True), net_trend, "#279968", "Inflows less outflows"),
        ("Credit utilisation", "Not available" if util is None else f"{util:.1f}%", util_trend, "#e89935", "Revolving exposure history")):
        tiles.append(f'<section class="cd-trend"><div><label>{label}</label><b>{value}</b><span>{caption}</span></div>{sparkline(series, color, caption)}</section>')
    html = f'<div class="customer-dashboard"><div class="cd-grid">{profile}{risk}{financial}{monitoring}{pillars}{alert_card}</div><div class="cd-trends">{"".join(tiles)}</div><div class="cd-summary"><span>Assessment summary</span><p>{text(result.summary)}</p></div></div>'
    st.markdown(html, unsafe_allow_html=True)
