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
    .block-container {max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem;}
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
    [data-testid="stMetricValue"] {font-size: 1.65rem; font-weight: 700; color: #172b4d;}
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
