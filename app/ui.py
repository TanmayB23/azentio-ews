"""Small presentation components; dynamic HTML is always escaped."""
from html import escape
import streamlit as st

BAND_COLORS = {
    "Low": ("#e8f5ee", "#17633c"),
    "Medium": ("#fff5d6", "#855c00"),
    "High": ("#fff0e5", "#a54912"),
    "Critical": ("#fdebed", "#ac2538"),
    "Insufficient data": ("#edf0f5", "#526176"),
}


def apply_styles():
    st.markdown("""<style>
    /* Streamlit's native fixed toolbar must not cover the scrolling workspace.
       Keep its sidebar opener usable when the navigation is collapsed. */
    [data-testid="stHeader"] {
        position: absolute; height: 0; background: transparent; pointer-events: none;
    }
    [data-testid="stHeader"] [data-testid="stToolbar"] {visibility: hidden;}
    [data-testid="stHeader"] [data-testid="stExpandSidebarButton"] {
        visibility: visible; pointer-events: auto; background: #f5f7fb;
        border: 1px solid #dce4ef; border-radius: 8px;
    }
    .block-container {max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem;}
    .stApp:has([data-testid="stExpandSidebarButton"]) .block-container {padding-top: 4.5rem;}
    h1 {font-size: 2rem !important; letter-spacing: -.055rem; font-weight: 750 !important;}
    h2, h3 {letter-spacing: -.025rem;}
    [data-testid="stSidebar"] {background: #12233f; border-right: 1px solid #223956;}
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stCaption {color: #e5edfa !important;}
    [data-testid="stSidebar"] [data-baseweb="select"] * {color: #172b4d;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        padding: .6rem .8rem; border-radius: 8px; margin-bottom: .2rem; transition: background .15s;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {background: #203959;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {background: #254876;}
    [data-testid="stMetric"] {background: white; padding: 1.15rem 1.3rem;
        border: 1px solid #e2e8f2; border-radius: 12px; box-shadow: 0 3px 12px #142b4c04;}
    [data-testid="stMetricLabel"] p {color: #61718a; font-size: .82rem; font-weight: 600;}
    [data-testid="stMetricValue"] {font-size: 1.65rem; font-weight: 700; color: #172b4d; white-space: normal; overflow-wrap: anywhere;}
    [data-testid="stMetricValue"] > div {white-space: normal; overflow: visible; text-overflow: clip;}
    [data-testid="stVerticalBlockBorderWrapper"] > div {border-color: #e2e8f2 !important; border-radius: 12px;}
    [data-testid="stDataFrame"] {border: 1px solid #e2e8f2; border-radius: 10px; overflow: hidden;}
    .stButton > button, .stDownloadButton > button {border-radius: 8px; font-weight: 600;}
    [data-baseweb="tab-list"] {gap: 1.5rem; border-bottom: 1px solid #dce4ef; margin: 1rem 0;}
    [data-baseweb="tab"] {font-weight: 600;}
    .ews-eyebrow {font-size: .7rem; letter-spacing: .14em; color: #627792; font-weight: 700; margin: .6rem 0 .2rem;}
    .ews-description {color: #61718a; font-size: .95rem; margin: -.6rem 0 1.5rem; max-width: 760px;}
    .ews-topbar {display: flex; justify-content: space-between; align-items: center;
        border-bottom: 1px solid #e0e7f1; padding-bottom: 1rem; margin-bottom: 1.5rem; gap: 1rem; flex-wrap: wrap;}
    .ews-topbar strong {font-size: .88rem; letter-spacing: .03em;}
    .ews-topbar span {font-size: .78rem; color: #65748a;}
    .ews-badge {display: inline-block; padding: .35rem .7rem; border-radius: 6px; font-size: .76rem; font-weight: 700;}
    .ews-empty {padding: 2rem; background: white; border: 1px dashed #c6d3e5; border-radius: 12px; margin: 1rem 0;}
    .ews-empty h3 {font-size: 1.1rem; margin: 0 0 .5rem;}
    .ews-empty p {color: #61718a; margin: 0;}
    .ews-brand {color: white; font-size: 1.65rem; font-weight: 800; letter-spacing: -.05rem; margin-bottom: .2rem;}
    .ews-brand span {color: #79aaff;}
    /* Customer workspace: compact card grid inspired by the reference dashboard. */
    .block-container:has(.customer-dashboard) {max-width: 1700px; padding-top: 1.25rem;}
    .block-container:has(.customer-dashboard) h1 {font-size: 1.75rem !important;}
    .block-container:has(.customer-dashboard) .ews-description {margin-bottom: .3rem;}
    .customer-dashboard {font-family: inherit; color: #13223c;}
    .cd-grid {display: grid; grid-template-columns: 1.13fr 1fr 1.13fr; gap: 16px;}
    .cd-card {min-width: 0; background: #fff; border: 1px solid #e4e8ee; border-radius: 12px;
        padding: 20px; box-shadow: 0 2px 5px #10243b05;}
    .customer-dashboard .cd-card h3 {font-size: 16px; font-weight: 700; margin: 0 0 18px; padding: 0; letter-spacing: -.02em;}
    .cd-identity {display: flex; align-items: center; gap: 14px; margin-bottom: 18px;}
    .cd-identity h4 {font-size: 1rem; font-weight: 700; margin: 0 0 4px; padding: 0; line-height: 1.4;}
    .cd-building {display: grid; place-items: center; flex: 0 0 50px; height: 52px;
        border-radius: 9px; background: #1260e8; color: white; font-size: 2rem;}
    .cd-muted {display: block; color: #6f7d91; font-size: .75rem; line-height: 1.5;}
    .cd-profile-grid {display: grid; grid-template-columns: 1fr 1.15fr; gap: 14px 18px; margin-bottom: 16px;}
    .customer-dashboard .cd-card label, .customer-dashboard .cd-trend label {display: block; color: #68788e; font-size: 12px; margin-bottom: 7px; line-height: 1.4;}
    .customer-dashboard .cd-profile-grid strong, .customer-dashboard .cd-pair strong {font-size: 13px; font-weight: 600; line-height: 1.5;}
    .cd-avatar {display: inline-grid; place-items: center; background: #eef2f8; color: #315078;
        width: 25px; height: 25px; border-radius: 50%; font-size: .58rem; margin-right: 5px;}
    .cd-divider {border-top: 1px solid #edf0f4; padding-top: 14px;}
    .cd-pair {display: grid; grid-template-columns: 1fr 1fr; gap: 16px;}
    .cd-pair b {font-size: 1.3rem; font-weight: 700;}
    .cd-assessment {display: flex; gap: 8px; align-items: center; min-height: 174px; margin-bottom: 14px;}
    .cd-gauge {width: 62%; max-width: 240px; overflow: visible; flex-shrink: 1;}
    .cd-gauge-value {font-size: 40px; font-weight: 750; fill: #11213c;}
    .cd-gauge-label {font-size: 13px; fill: #7a8798;}
    .cd-risk-meta {flex: 1; min-width: 85px;}
    .cd-risk-meta label {margin-top: 17px; margin-bottom: 3px;}
    .cd-risk-meta > strong {font-size: 1.45rem; display: block; margin-bottom: 7px;}
    .cd-chip {display: inline-block; font-size: .72rem; font-weight: 700; border-radius: 20px; padding: 6px 10px; line-height: 1.5;}
    .cd-document {display: flex; align-items: center; gap: 9px; padding-bottom: 14px; margin-bottom: 6px; border-bottom: 1px solid #edf0f4;}
    .cd-document strong {display: block; font-size: .79rem; font-weight: 600;}
    .cd-file {display: grid; place-items: center; width: 32px; height: 38px; border-radius: 4px; background: #f2f5f9; color: #53677e;}
    .cd-source {margin-left: auto; color: #33815e; font-size: .65rem; white-space: nowrap;}
    .customer-dashboard .cd-table {border-collapse: collapse; width: 100%; font-size: 13px; border: 0;}
    .customer-dashboard .cd-table th {text-align: left; font-size: 12px; font-weight: 600; color: #728097; padding: 9px 0;}
    .customer-dashboard .cd-table td {padding: 10px 0; border-top: 1px solid #f0f2f6; vertical-align: top; line-height: 1.35;}
    .customer-dashboard .cd-table th, .customer-dashboard .cd-table td {border: 0; border-bottom: 1px solid #edf0f4;}
    .cd-table th:last-child, .cd-table td:last-child {text-align: right;}
    .cd-table td:last-child {font-weight: 600;}
    .cd-signal-name {font-size: 11px; margin-top: 3px; max-width: 210px;}
    .cd-monitoring td:first-child {width: 62%; padding-right: 8px;}
    .cd-monitoring td:nth-child(2) {padding-right: 10px;}
    .cd-monitoring td:last-child {font-size: .7rem; color: #38557b;}
    .customer-dashboard p.cd-footnote {font-size: 11px; color: #8490a1; margin: 10px 0 0; line-height: 1.5;}
    .cd-pillar {margin: 0 0 16px;}
    .cd-pillar > div:first-child {display: flex; justify-content: space-between; font-size: .79rem; margin-bottom: 8px; gap: 8px;}
    .cd-pillar strong {font-weight: 650;}
    .cd-pillar small {font-size: .65rem; color: #8a94a3; font-weight: 400;}
    .cd-track {height: 7px; border-radius: 5px; background: #eff3f8; overflow: hidden;}
    .cd-track span {display: block; height: 100%; border-radius: 5px;}
    .cd-coverage {border-top: 1px solid #edf0f4; padding-top: 14px; margin-top: 18px; display: flex; justify-content: space-between; font-size: .77rem;}
    .cd-alert {display: flex; gap: 11px; padding: 10px 0 13px; border-bottom: 1px solid #edf0f4;}
    .cd-alert:first-of-type {padding-top: 0;}
    .cd-alert strong {display: block; font-size: 13px; font-weight: 650;}
    .customer-dashboard .cd-alert p {font-size: 12px; color: #738197; margin: 5px 0 0; line-height: 1.5;}
    .cd-alert-icon {display: grid; place-items: center; flex: 0 0 22px; height: 22px; border: 1.5px solid #e9973b;
        border-radius: 50%; color: #d88224; font-size: .75rem; font-weight: 700;}
    .cd-alert-footer {font-size: .72rem; color: #2b63bc; padding-top: 14px;}
    .cd-trends {display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); margin-top: 16px;
        background: white; border: 1px solid #e4e8ee; border-radius: 12px; padding: 17px 0;}
    .cd-trend {padding: 0 20px; display: flex; justify-content: space-between; align-items: center; gap: 10px; border-right: 1px solid #edf0f4; min-width: 0;}
    .cd-trend:last-child {border: 0;}
    .cd-trend b {font-size: 1.4rem; display: block; font-weight: 750; white-space: normal;}
    .cd-trend span {display: block; font-size: .65rem; color: #8591a2; margin-top: 6px;}
    .cd-trend > div {min-width: 0;}
    .cd-spark {width: 39%; flex-shrink: 1; max-width: 160px;}
    .cd-spark-empty {font-size: .65rem !important; max-width: 80px; text-align: right;}
    .cd-summary {display: flex; align-items: baseline; gap: 15px; margin-top: 14px; padding: 13px 17px; background: #edf3fd; border-radius: 8px;}
    .cd-summary > span {color: #365885; font-size: .73rem; font-weight: 700; white-space: nowrap;}
    .customer-dashboard .cd-summary p {font-size: 13px; color: #526b8b; margin: 0; line-height: 1.6;}
    @media (max-width: 1150px) {
        .cd-grid {grid-template-columns: 1fr 1fr;}
        .cd-trend {padding: 0 12px;}
        .cd-spark {width: 30%;}
    }
    @media (max-width: 700px) {
        .cd-grid {grid-template-columns: 1fr; gap: 12px;}
        .cd-card {padding: 18px;}
        .cd-trends {grid-template-columns: 1fr; padding: 0;}
        .cd-trend {border-right: 0; border-bottom: 1px solid #edf0f4; padding: 16px 18px;}
        .cd-trend:last-child {border: 0;}
        .cd-spark {width: 40%;}
        .cd-summary {display: block;}
        .cd-summary p {margin-top: 6px;}
    }
    @media (max-width: 700px) {
        .block-container {padding-left: 1rem; padding-right: 1rem;}
        h1 {font-size: 1.6rem !important;}
        [data-testid="stMetric"] {padding: .85rem;}
    }
    </style>""", unsafe_allow_html=True)


def page_header(title, description, section):
    st.markdown(f'<div class="ews-eyebrow">{escape(section.upper())}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="ews-description">{escape(description)}</p>', unsafe_allow_html=True)


def topbar(region, mode):
    st.markdown(f'<div class="ews-topbar"><strong>Early Warning System</strong>'
        f'<span>{escape(region)} &nbsp; / &nbsp; {escape(mode)} workspace &nbsp; / &nbsp; 31 Oct 2026</span></div>', unsafe_allow_html=True)


def badge(label):
    bg, fg = BAND_COLORS.get(label, BAND_COLORS["Insufficient data"])
    st.markdown(f'<span class="ews-badge" style="background:{bg};color:{fg}">{escape(label)}</span>', unsafe_allow_html=True)


def empty_state(title, description):
    st.markdown(f'<div class="ews-empty"><h3>{escape(title)}</h3><p>{escape(description)}</p></div>', unsafe_allow_html=True)


def band_style(value):
    bg, fg = BAND_COLORS.get(value, BAND_COLORS["Insufficient data"])
    return f"background-color: {bg}; color: {fg}; font-weight: 600"
