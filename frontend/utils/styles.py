"""Shared CSS injected into every MeetRecall AI page."""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
/* Page background */
[data-testid="stAppViewContainer"] > .main {
    background-color: #0f172a;
}

/* Sidebar dark theme */
[data-testid="stSidebar"] {
    background: linear-gradient(175deg, #1e1b4b 0%, #312e81 100%) !important;
}
[data-testid="stSidebar"] * {
    color: rgba(255,255,255,0.9) !important;
}
[data-testid="stSidebar"] .stTextInput input {
    background: rgba(255,255,255,0.1) !important;
    border: 1px solid rgba(255,255,255,0.25) !important;
    color: white !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] .stSelectbox > div > div {
    background: rgba(255,255,255,0.1) !important;
    border: 1px solid rgba(255,255,255,0.25) !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.12) !important;
    border: 1px solid rgba(255,255,255,0.28) !important;
    color: white !important;
    border-radius: 8px !important;
    width: 100%;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.22) !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: #1e293b;
    border-radius: 12px;
    padding: 16px 20px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    border: 1px solid #334155;
}
[data-testid="stMetricValue"] {
    font-size: 1.7rem !important;
    font-weight: 800 !important;
    color: #f1f5f9 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.77rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.6px !important;
    text-transform: uppercase !important;
    color: #94a3b8 !important;
}

/* Primary button */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    border: none !important;
    color: white !important;
    font-weight: 700 !important;
    border-radius: 10px !important;
    padding: 10px 28px !important;
    font-size: 15px !important;
    transition: transform 0.15s, box-shadow 0.15s !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(99,102,241,0.4) !important;
}

/* Step header */
.step-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 20px 0 10px 0;
}
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 34px;
    height: 34px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: white;
    font-weight: 800;
    font-size: 16px;
    flex-shrink: 0;
}
.step-title {
    font-size: 18px;
    font-weight: 700;
    color: #f1f5f9;
}

/* Info / success / warning boxes */
.info-box {
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(129,140,248,0.4);
    border-radius: 12px;
    padding: 14px 18px;
    color: #c7d2fe;
    font-size: 14px;
    line-height: 1.6;
    margin: 10px 0;
}
.success-box {
    background: rgba(34,197,94,0.12);
    border: 1px solid rgba(74,222,128,0.4);
    border-radius: 12px;
    padding: 14px 18px;
    color: #bbf7d0;
    font-size: 14px;
    line-height: 1.6;
    margin: 10px 0;
}
.warn-box {
    background: rgba(245,158,11,0.12);
    border: 1px solid rgba(252,211,77,0.4);
    border-radius: 12px;
    padding: 14px 18px;
    color: #fde68a;
    font-size: 14px;
    line-height: 1.6;
    margin: 10px 0;
}

/* Speaker segments */
.seg-block {
    padding: 12px 16px;
    border-radius: 10px;
    margin-bottom: 8px;
    border-left: 4px solid;
}
.seg-block.spk-0 { background:rgba(59,130,246,0.12); border-color:#3b82f6; }
.seg-block.spk-1 { background:rgba(168,85,247,0.12); border-color:#a855f7; }
.seg-block.spk-2 { background:rgba(34,197,94,0.12); border-color:#22c55e; }
.seg-block.spk-3 { background:rgba(249,115,22,0.12); border-color:#f97316; }
.seg-block.spk-4 { background:rgba(236,72,153,0.12); border-color:#ec4899; }
.seg-block.spk-5 { background:rgba(20,184,166,0.12); border-color:#14b8a6; }
.spk-name { font-size:12px; font-weight:700; margin-bottom:3px; }
.spk-name.spk-0 { color:#60a5fa; }
.spk-name.spk-1 { color:#c084fc; }
.spk-name.spk-2 { color:#4ade80; }
.spk-name.spk-3 { color:#fb923c; }
.spk-name.spk-4 { color:#f472b6; }
.spk-name.spk-5 { color:#2dd4bf; }
.seg-ts   { font-size:11px; color:#94a3b8; margin-left:6px; }
.seg-text { font-size:14px; color:#cbd5e1; line-height:1.65; margin:0; }

/* Summary card */
.summary-card {
    background: #1e293b;
    border-radius: 16px;
    padding: 24px 28px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    border: 1px solid #334155;
    margin-bottom: 20px;
}
.summary-item {
    display: flex;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #334155;
    font-size: 14px;
    color: #cbd5e1;
}
.summary-item:last-child { border-bottom: none; }
.summary-key {
    font-weight: 700;
    color: #a5b4fc;
    min-width: 130px;
    flex-shrink: 0;
}

/* Feature cards (landing) */
.feat-card {
    background: #1e293b;
    border-radius: 18px;
    padding: 28px 22px;
    text-align: center;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    border: 1px solid #334155;
    height: 100%;
}
.feat-title { font-size:17px; font-weight:700; color:#f1f5f9; margin-bottom:8px; }
.feat-desc  { font-size:13px; color:#94a3b8; line-height:1.65; }

/* Topic cards */
.topic-card {
    background: #1e293b;
    border-radius: 12px;
    padding: 18px 22px;
    margin: 10px 0;
    border-left: 5px solid;
    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
}
.tc-0{border-color:#6366f1;} .tc-1{border-color:#ec4899;}
.tc-2{border-color:#22c55e;} .tc-3{border-color:#f97316;}
.tc-4{border-color:#a855f7;} .tc-5{border-color:#14b8a6;}
.tc-6{border-color:#eab308;} .tc-7{border-color:#ef4444;}

/* Processing box */
.proc-box {
    text-align: center;
    padding: 36px 24px;
    background: #1e293b;
    border-radius: 16px;
    border: 1px solid rgba(252,211,77,0.4);
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
}

/* Chat: user on the right as a bubble, assistant on the left */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse;
    background: transparent;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
  [data-testid="stChatMessageContent"] {
    flex: 0 1 auto;
    max-width: 75%;
    margin-left: auto !important;
    margin-right: 0 !important;
    background: rgba(99,102,241,0.25);
    border: 1px solid rgba(129,140,248,0.35);
    border-radius: 14px 4px 14px 14px;
    padding: 8px 14px;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
  [data-testid="stChatMessageContent"] {
    max-width: 85%;
}

/* Custom avatars (Material icons) are marked as "custom" by Streamlit, so the role is read from aria-label */
[data-testid="stChatMessage"]:has(.mr-user) {
    flex-direction: row-reverse;
    background: transparent;
}
[data-testid="stChatMessage"]:has(.mr-user) [data-testid="stChatMessageContent"] {
    flex: 0 1 auto;
    max-width: 75%;
    margin-left: auto !important;
    margin-right: 0 !important;
    background: rgba(99,102,241,0.25);
    border: 1px solid rgba(129,140,248,0.35);
    border-radius: 14px 4px 14px 14px;
    padding: 8px 14px;
}
[data-testid="stChatMessage"]:not(:has(.mr-user)) [data-testid="stChatMessageContent"] {
    max-width: 90%;
}
.mr-user { display: none; }
[data-testid="stChatMessageAvatarCustom"] {
    background: linear-gradient(135deg, #4E72C2, #8b5cf6) !important;
    color: #ffffff !important;
}

/* Divider */
hr { border-color: #334155 !important; margin: 24px 0 !important; }
</style>
"""


# Chat avatars: Material icons built into Streamlit (https://fonts.google.com/icons). The sparkle is
# the same idea as Gemini's, the person icon is for the user.
ASSISTANT_AVATAR = ":material/auto_awesome:"
USER_AVATAR = ":material/person:"
# Streamlit marks custom avatars as "custom" for both roles and sets no aria-label, so user messages carry
# this invisible marker and the CSS finds them with :has().
USER_MARK = '<span class="mr-user"></span>'


def user_html(text: str) -> str:
    """User text with the invisible role marker in front. One markdown element, so the bubble has no
    extra empty row. The text is escaped because it is rendered with unsafe_allow_html=True."""
    import html
    return USER_MARK + html.escape(text or "", quote=False)


def inject() -> None:
    """Inject shared CSS into the current Streamlit page."""
    st.markdown(_CSS, unsafe_allow_html=True)
