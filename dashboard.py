"""
Macro Rates Dashboard - Streamlit web app.
Uses the same data logic as fetch_macro_data.py. Run: streamlit run dashboard.py
"""

import os
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

import requests

from fetch_macro_data import (
    get_fred_api_key,
    get_bcch_credentials,
    get_notion_credentials,
    fetch_fred_series,
    fetch_bcch_series,
    compute_all_spreads,
)


def _cur(r):
    """Current value from rate result (2- or 6-tuple)."""
    if not r or len(r) < 1:
        return None
    return r[0]


def _val_1w(r):
    if not r or len(r) < 3:
        return None
    return r[2]


def _val_1m(r):
    if not r or len(r) < 5:
        return None
    return r[4]


def _history(r) -> List[Tuple[str, float]]:
    """Last element of fetch tuple: list of (date_str, value) for ~12m sparklines."""
    if not r or len(r) < 7:
        return []
    h = r[6]
    return h if isinstance(h, list) else []


def _history_df(points: List[Tuple[str, float]]) -> Optional[pd.DataFrame]:
    if not points:
        return None
    df = pd.DataFrame(points, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def _spread_history(left_df: pd.DataFrame, right_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Align two series by date (as-of backward) and return date + spread = left - right."""
    if left_df is None or right_df is None or left_df.empty or right_df.empty:
        return None
    L = left_df.rename(columns={"value": "left"}).sort_values("date")
    R = right_df.rename(columns={"value": "right"}).sort_values("date")
    merged = pd.merge_asof(L, R, on="date", direction="backward")
    merged = merged.dropna(subset=["left", "right"])
    if merged.empty:
        return None
    merged["spread"] = merged["left"] - merged["right"]
    return merged[["date", "spread"]]


def render_spread_sparkline(
    left_hist: List[Tuple[str, float]],
    right_hist: List[Tuple[str, float]],
    current_spread: Optional[float] = None,
    chart_key: str = "spark",
):
    """Compact ~12m spread history: line color matches spread sign; dotted 12m average + caption below."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.caption("12m history: install plotly")
        return

    left_df = _history_df(left_hist)
    right_df = _history_df(right_hist)
    mdf = _spread_history(left_df, right_df) if left_df is not None and right_df is not None else None
    if mdf is None or mdf.empty:
        st.caption("12m history: —")
        return

    spreads_arr = mdf["spread"].values
    avg_v = float(spreads_arr.mean())

    if current_spread is not None:
        if current_spread > 0:
            line_color = "#2e7d32"
        elif current_spread < 0:
            line_color = "#c62828"
        else:
            line_color = "#555555"
    else:
        line_color = "#444444"

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=mdf["date"],
            y=mdf["spread"],
            mode="lines",
            line=dict(color=line_color, width=2),
            hovertemplate="%{y:+.2f}%<extra></extra>",
            name="",
        )
    )
    fig.add_hline(y=avg_v, line_dash="dot", line_color="rgba(0,0,0,0.45)", line_width=1)
    fig.update_layout(
        height=145,
        margin=dict(l=0, r=8, t=4, b=28),
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=9, color="#888888"),
            tickformat="%b",
            nticks=5,
            showline=False,
        ),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, showline=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=chart_key)
    # Caption (not Plotly annotation): Plotly treats "%" in annotation text as printf-style,
    # which breaks labels like "+0.45%". Streamlit caption shows the value reliably.
    st.caption(f"12m avg: {avg_v:+.2f}%")


# ---------------------------------------------------------------------------
# Notion Daily View (requests → Notion API, no SDK)
# ---------------------------------------------------------------------------

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
NOTION_PROP_DATE = "Date"
NOTION_PROP_NOTE = "Note"
_NOTION_TEXT_CHUNK = 2000  # Notion rich_text / title segment limit


def _normalize_notion_database_id(raw: str) -> str:
    """Accept UUID with or without hyphens (as copied from Notion URLs)."""
    s = raw.replace("-", "").replace(" ", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return raw.strip()


def _notion_headers(token: str) -> dict:
    # Bearer token is passed verbatim (Notion uses secret_* or ntn_* prefixes; do not alter).
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def _notion_note_property_value(note_text: str) -> dict:
    """
    Build API payload for the Note column.
    Default: rich_text (Notion "Text"). If your DB uses the primary Title column named "Note",
    set NOTION_NOTE_AS_TITLE=true in .env.
    """
    use_title = os.environ.get("NOTION_NOTE_AS_TITLE", "").strip().lower() in ("1", "true", "yes")
    chunks = [note_text[i : i + _NOTION_TEXT_CHUNK] for i in range(0, len(note_text), _NOTION_TEXT_CHUNK)]
    if not chunks:
        chunks = [""]
    if use_title:
        return {"title": [{"type": "text", "text": {"content": chunks[0]}}]}
    return {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}


def notion_create_daily_page(token: str, database_id: str, note_text: str, d: date) -> Tuple[bool, str]:
    """Create a row in the Notion database with Date + Note. Returns (success, error_message)."""
    db_id = _normalize_notion_database_id(database_id)
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            NOTION_PROP_DATE: {"date": {"start": d.isoformat()}},
            NOTION_PROP_NOTE: _notion_note_property_value(note_text),
        },
    }
    try:
        resp = requests.post(
            f"{NOTION_API_BASE}/pages",
            headers=_notion_headers(token),
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        return False, str(e)
    if resp.status_code in (200, 201):
        return True, ""
    try:
        body = resp.json()
        msg = body.get("message", resp.text)
    except Exception:
        msg = resp.text or f"HTTP {resp.status_code}"
    return False, msg


def _notion_extract_property_plain(prop: Optional[dict]) -> str:
    if not prop or not isinstance(prop, dict):
        return ""
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(p.get("plain_text", "") for p in (prop.get("title") or []))
    if ptype == "rich_text":
        return "".join(p.get("plain_text", "") for p in (prop.get("rich_text") or []))
    if ptype == "date":
        d = prop.get("date")
        if not d:
            return ""
        start = d.get("start") or ""
        return start[:10] if start else ""
    return ""


def notion_query_recent_notes(
    token: str, database_id: str, limit: int = 5
) -> Tuple[List[Tuple[str, str]], str]:
    """
    Query the database sorted by Date descending. Returns (list of (date_str, note_text), error_message).
    """
    db_id = _normalize_notion_database_id(database_id)
    payload = {
        "page_size": limit,
        "sorts": [{"property": NOTION_PROP_DATE, "direction": "descending"}],
    }
    try:
        resp = requests.post(
            f"{NOTION_API_BASE}/databases/{db_id}/query",
            headers=_notion_headers(token),
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        return [], str(e)
    if resp.status_code != 200:
        try:
            msg = resp.json().get("message", resp.text)
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        return [], msg
    data = resp.json()
    out: List[Tuple[str, str]] = []
    for page in data.get("results") or []:
        props = page.get("properties") or {}
        date_s = _notion_extract_property_plain(props.get(NOTION_PROP_DATE))
        note_s = _notion_extract_property_plain(props.get(NOTION_PROP_NOTE))
        out.append((date_s or "—", note_s or "—"))
    return out, ""


# 2026 meeting dates: (month, day_start, day_end) for Fed; (month, day) for BCCh
FED_2026 = [(1, 27, 28), (3, 17, 18), (4, 28, 29), (6, 16, 17), (7, 28, 29), (9, 15, 16), (10, 27, 28), (12, 8, 9)]
BCCH_2026 = [(1, 26), (3, 24), (4, 27), (6, 16), (7, 27), (9, 8), (10, 26), (12, 15)]
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _meeting_last_next(meeting_dates_list, single_day=False):
    """Return (last_meeting_str, next_meeting_str) for 2026. meeting_dates_list: list of (m, d) or (m, d1, d2)."""
    today = date.today()
    if today.year != 2026:
        return None, None
    last_str, next_str = None, None
    for t in meeting_dates_list:
        if single_day:
            m, d = t[0], t[1]
            d_ = date(2026, m, d)
            label = f"{MONTHS[m]} {d}"
        else:
            m, d1, d2 = t[0], t[1], t[2]
            d_ = date(2026, m, d1)
            label = f"{MONTHS[m]} {d1}–{d2}"
        if d_ <= today:
            last_str = label
        elif d_ > today and next_str is None:
            next_str = label
    return last_str, next_str


def get_fed_meeting_line():
    last, next_ = _meeting_last_next(FED_2026, single_day=False)
    if last is None and next_ is None:
        return None
    return f"Last meeting: {last or '—'} — Next meeting: {next_ or '—'}"


def get_bcch_meeting_line():
    last, next_ = _meeting_last_next(BCCH_2026, single_day=True)
    if last is None and next_ is None:
        return None
    return f"Last meeting: {last or '—'} — Next meeting: {next_ or '—'}"


def compute_anomalies(fred_results, bcch_results, spreads):
    """
    Return list of (severity, message). severity in ("warning", "alert").
    Red alerts only: US 10Y weekly ≥20bps, any yield curve inversion/reversion, sovereign spread 1m ≥30bps.
    Yellow only: US 10Y cross 4.00% threshold.
    """
    anomalies = []
    us_10y = fred_results.get("US 10Y Treasury Yield") if fred_results else None
    us_2y = fred_results.get("US 2Y Treasury Yield") if fred_results else None
    cl_10y = bcch_results.get("Chile BCP/BTP 10Y Yield (CLP)") if bcch_results else None
    cl_2y = bcch_results.get("Chile BCP/BTP 2Y Yield (CLP)") if bcch_results else None

    # US 10Y: red only if weekly move ≥20bps; yellow only for 4% cross
    if us_10y:
        cur = _cur(us_10y)
        v1w = _val_1w(us_10y)
        v1m = _val_1m(us_10y)
        if cur is not None and v1w is not None:
            move_bps = abs(cur - v1w) * 100
            if move_bps >= 20:
                anomalies.append(("alert", f"US 10Y: weekly move {move_bps:.0f} bps (≥20 bps)."))
        if cur is not None:
            for name, prev in [("1w ago", v1w), ("1m ago", v1m)]:
                if prev is not None and (cur - 4.0) * (prev - 4.0) < 0:
                    anomalies.append(("warning", f"US 10Y: rate crossed 4.00% (now {cur:.2f}%, {name} {prev:.2f}%)."))
                    break

    # Chile 10Y vs US 10Y: red only if 1m change ≥30bps
    spread_cl_us = next((s for s in spreads if "Chile 10Y vs US 10Y" in s[0]), None)
    if spread_cl_us and cl_10y and us_10y:
        cur_spread = spread_cl_us[1]
        c10_1m = _val_1m(cl_10y)
        v10_1m = _val_1m(us_10y)
        if cur_spread is not None and c10_1m is not None and v10_1m is not None:
            spread_1m = c10_1m - v10_1m
            chg_bps = abs(cur_spread - spread_1m) * 100
            if chg_bps >= 30:
                anomalies.append(("alert", f"Chile 10Y vs US 10Y spread: 1m change {chg_bps:.0f} bps (≥30 bps)."))

    # US 2y/10y: red if spread crosses zero
    spread_us = next((s for s in spreads if s[0] == "US 2Y/10Y spread (10Y - 2Y)"), None)
    if spread_us and us_2y and us_10y:
        cur_s = spread_us[1]
        s1w = _val_1w(us_10y) - _val_1w(us_2y) if (_val_1w(us_10y) is not None and _val_1w(us_2y) is not None) else None
        s1m = _val_1m(us_10y) - _val_1m(us_2y) if (_val_1m(us_10y) is not None and _val_1m(us_2y) is not None) else None
        if cur_s is not None:
            for label, prev in [("1w ago", s1w), ("1m ago", s1m)]:
                if prev is not None and cur_s * prev < 0:
                    anomalies.append(("alert", f"US yield curve (2y/10y): spread crossed zero (inversion/reversion); now {cur_s:+.2f}%, {label} {prev:+.2f}%."))
                    break

    # Chile 10y/2y: red if spread crosses zero
    spread_cl = next((s for s in spreads if s[0] == "Chile yield curve spread (10Y - 2Y)"), None)
    if spread_cl and cl_10y and cl_2y:
        cur_s = spread_cl[1]
        c10_1m, c2_1m = _val_1m(cl_10y), _val_1m(cl_2y)
        s1m = (c10_1m - c2_1m) if (c10_1m is not None and c2_1m is not None) else None
        if cur_s is not None and s1m is not None and cur_s * s1m < 0:
            anomalies.append(("alert", f"Chile yield curve (10y-2y): spread crossed zero; now {cur_s:+.2f}%, 1m ago {s1m:+.2f}%."))

    return anomalies


def load_data():
    """Fetch all data from FRED and BCCh. Returns (fred_results, bcch_results, spreads) or (None, None, [])."""
    api_key = get_fred_api_key()
    bcch_user, bcch_pass = get_bcch_credentials()
    if not api_key or not bcch_user or not bcch_pass:
        return None, None, []
    fred_results = fetch_fred_series(api_key)
    bcch_results = fetch_bcch_series(bcch_user, bcch_pass)
    spreads = compute_all_spreads(fred_results or {}, bcch_results or {})
    return fred_results, bcch_results, spreads


def metric_card(label: str, value, date_str: str, is_spread: bool = False):
    """Render a single metric: value as main number, date below. If is_spread, color value green/red."""
    if value is None:
        val_display = "—"
        color = None
    else:
        val_display = f"{value:+.2f}%" if is_spread else f"{value:.2f}%"
        color = "green" if (is_spread and value > 0) else ("red" if (is_spread and value < 0) else None)
    with st.container():
        st.markdown(f"**{label}**")
        if color:
            st.markdown(f"<span style='font-size: 1.75rem; font-weight: 600; color: {color};'>{val_display}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"<span style='font-size: 1.75rem; font-weight: 600;'>{val_display}</span>", unsafe_allow_html=True)
        st.caption(f"As of {date_str or 'N/A'}")


def metric_card_with_trend(
    label: str,
    cur, cur_date,
    val_1w, date_1w,
    val_1m, date_1m,
    meeting_line: Optional[str] = None,
):
    """Render a rate metric: value, bps vs 1m (gray, ⚠ if |change|>10bps), direction arrow (red/green), date, optional meeting line."""
    with st.container():
        st.markdown(f"**{label}**")
        if cur is None:
            st.markdown("<span style='font-size: 1.75rem; font-weight: 600;'>—</span>", unsafe_allow_html=True)
            if meeting_line:
                st.markdown(f"<span style='font-size: 0.75rem; color: #888;'>{meeting_line}</span>", unsafe_allow_html=True)
            st.caption(f"As of {cur_date or 'N/A'}")
            return
        st.markdown(f"<span style='font-size: 1.75rem; font-weight: 600;'>{cur:.2f}%</span>", unsafe_allow_html=True)
        # One line: bps change vs 1m, gray; ⚠ only if |change| > 10 bps
        if val_1m is not None:
            bps = (cur - val_1m) * 100
            sign = "+" if bps >= 0 else "−"
            warn = "⚠ " if abs(bps) > 10 else ""
            st.markdown(
                f"<span style='font-size: 0.8rem; color: #888;'>{warn}{sign}{abs(bps):.0f} bps vs 1m</span>",
                unsafe_allow_html=True,
            )
        # Direction arrow: bond investor view — up = red, down = green
        if val_1m is not None and cur != val_1m:
            arrow = "↑" if cur > val_1m else "↓"
            color = "red" if cur > val_1m else "green"
            st.markdown(f"<span style='font-size: 1.1rem; font-weight: 600; color: {color};'>vs 1m {arrow}</span>", unsafe_allow_html=True)
        if meeting_line:
            st.markdown(f"<span style='font-size: 0.75rem; color: #888;'>{meeting_line}</span>", unsafe_allow_html=True)
        st.caption(f"As of {cur_date or 'N/A'}")


def main():
    st.set_page_config(page_title="Macro Rates Dashboard", page_icon="📊", layout="wide")
    st.title("Macro Rates Dashboard")

    # Session state: cache data until Refresh is clicked
    if "data_fetched" not in st.session_state:
        st.session_state.data_fetched = False
        st.session_state.fred_results = None
        st.session_state.bcch_results = None
        st.session_state.spreads = []
        st.session_state.load_error = None

    col_refresh, _ = st.columns([1, 4])
    with col_refresh:
        if st.button("Refresh", type="primary"):
            st.session_state.data_fetched = False
            st.session_state.fred_results = None
            st.session_state.bcch_results = None
            st.session_state.spreads = []
            st.session_state.load_error = None
            st.rerun()

    # Load data once per session (or after Refresh)
    if not st.session_state.data_fetched:
        st.session_state.data_fetched = True
        with st.spinner("Loading latest data…"):
            try:
                api_key = get_fred_api_key()
                bcch_user, bcch_pass = get_bcch_credentials()
                if not api_key or not bcch_user or not bcch_pass:
                    st.session_state.load_error = "Missing credentials. Set FRED_API_KEY, BCCH_USER, and BCCH_PASS in .env"
                else:
                    fred_results, bcch_results, spreads = load_data()
                    st.session_state.fred_results = fred_results or {}
                    st.session_state.bcch_results = bcch_results or {}
                    st.session_state.spreads = spreads or []
            except Exception as e:
                st.session_state.load_error = str(e)
        st.rerun()

    if st.session_state.get("load_error"):
        st.error(st.session_state.load_error)
        st.stop()

    fred_results = st.session_state.fred_results or {}
    bcch_results = st.session_state.bcch_results or {}
    spreads = st.session_state.spreads or []

    # --- Top banner: red alerts and yellow (4% only); else minimal "All clear" in gray ---
    anomalies = compute_anomalies(fred_results, bcch_results, spreads)
    if anomalies:
        for severity, msg in anomalies:
            if severity == "alert":
                st.error(f"**Alert:** {msg}")
            else:
                st.warning(f"**Warning:** {msg}")
    else:
        st.markdown("<span style='font-size: 0.85rem; color: #888;'>All clear ✓</span>", unsafe_allow_html=True)

    st.divider()

    # --- Yield curve visualization ---
    try:
        import plotly.graph_objects as go
        us_2y = fred_results.get("US 2Y Treasury Yield")
        us_10y = fred_results.get("US 10Y Treasury Yield")
        us_30y = fred_results.get("US 30Y Treasury Yield")
        cl_2y = bcch_results.get("Chile BCP/BTP 2Y Yield (CLP)")
        cl_5y = bcch_results.get("Chile BCP/BTP 5Y Yield (CLP)")
        cl_10y = bcch_results.get("Chile BCP/BTP 10Y Yield (CLP)")
        maturities_us = [2, 10, 30]
        maturities_cl = [2, 5, 10]
        us_now = [_cur(us_2y), _cur(us_10y), _cur(us_30y)] if us_2y and us_10y and us_30y else None
        us_1w = [_val_1w(us_2y), _val_1w(us_10y), _val_1w(us_30y)] if us_2y and us_10y and us_30y else None
        cl_now = [_cur(cl_2y), _cur(cl_5y), _cur(cl_10y)] if cl_2y and cl_5y and cl_10y else None
        cl_1w = [_val_1w(cl_2y), _val_1w(cl_5y), _val_1w(cl_10y)] if cl_2y and cl_5y and cl_10y else None
        fig = go.Figure()
        if us_now and all(x is not None for x in us_now):
            fig.add_trace(go.Scatter(x=maturities_us, y=us_now, mode="lines+markers", name="US (current)", line=dict(color="#1f77b4", width=2)))
        if us_1w and all(x is not None for x in us_1w):
            fig.add_trace(go.Scatter(x=maturities_us, y=us_1w, mode="lines+markers", name="US (1w ago)", line=dict(color="#1f77b4", width=1.5, dash="dot"), opacity=0.6))
        if cl_now and all(x is not None for x in cl_now):
            fig.add_trace(go.Scatter(x=maturities_cl, y=cl_now, mode="lines+markers", name="Chile (current)", line=dict(color="#ff7f0e", width=2)))
        if cl_1w and all(x is not None for x in cl_1w):
            fig.add_trace(go.Scatter(x=maturities_cl, y=cl_1w, mode="lines+markers", name="Chile (1w ago)", line=dict(color="#ff7f0e", width=1.5, dash="dot"), opacity=0.6))
        fig.update_layout(
            title="Yield curves: US vs Chile (current and 1 week ago)",
            xaxis_title="Maturity (years)",
            yaxis_title="Yield (%)",
            template="plotly_white",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=60, b=50),
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass

    st.divider()

    # --- US rates (with trend: 1w, 1m ago and direction arrow) ---
    st.subheader("United States (FRED)")
    us_cols = st.columns(4)
    for i, (label, row) in enumerate(fred_results.items()):
        with us_cols[i]:
            cur, cur_date = row[0], row[1] if len(row) >= 2 else None
            val_1w = row[2] if len(row) > 2 else None
            date_1w = row[3] if len(row) > 3 else None
            val_1m = row[4] if len(row) > 4 else None
            date_1m = row[5] if len(row) > 5 else None
            meeting = get_fed_meeting_line() if label == "US Federal Funds Rate" else None
            metric_card_with_trend(label, cur, cur_date, val_1w, date_1w, val_1m, date_1m, meeting_line=meeting)

    st.divider()

    # --- Chile rates (with trend) ---
    st.subheader("Chile (BCCh)")
    chile_cols = st.columns(4)
    for i, (label, row) in enumerate(bcch_results.items()):
        with chile_cols[i]:
            cur, cur_date = row[0], row[1] if len(row) >= 2 else None
            val_1w = row[2] if len(row) > 2 else None
            date_1w = row[3] if len(row) > 3 else None
            val_1m = row[4] if len(row) > 4 else None
            date_1m = row[5] if len(row) > 5 else None
            meeting = get_bcch_meeting_line() if label == "Chile Central Bank Policy Rate (TPM)" else None
            metric_card_with_trend(label, cur, cur_date, val_1w, date_1w, val_1m, date_1m, meeting_line=meeting)

    st.divider()

    # --- Spreads (color coded) + 12m sparklines (same order as compute_all_spreads) ---
    st.subheader("Spreads")
    spark_pairs = [
        ("US 10Y Treasury Yield", "US 2Y Treasury Yield", fred_results, fred_results),
        ("Chile BCP/BTP 10Y Yield (CLP)", "US 10Y Treasury Yield", bcch_results, fred_results),
        ("Chile BCP/BTP 2Y Yield (CLP)", "US 2Y Treasury Yield", bcch_results, fred_results),
        ("Chile BCP/BTP 10Y Yield (CLP)", "Chile BCP/BTP 2Y Yield (CLP)", bcch_results, bcch_results),
    ]
    spread_cols = st.columns(4)
    for i, (label, value, date_str) in enumerate(spreads):
        with spread_cols[i]:
            metric_card(label, value, date_str or "N/A", is_spread=True)
            if i < len(spark_pairs):
                lk, rk, d_left, d_right = spark_pairs[i]
                lh = _history(d_left.get(lk))
                rh = _history(d_right.get(rk))
                render_spread_sparkline(lh, rh, current_spread=value, chart_key=f"spread-spark-{i}")

    st.divider()

    # --- Daily View (Notion database) ---
    st.subheader("Daily View")
    notion_token, notion_db_id = get_notion_credentials()

    if st.session_state.pop("notion_saved_ok", None):
        st.success("Saved to Notion.")

    note = st.text_input("Note", key="daily_note", placeholder="Add a note...", label_visibility="collapsed")
    if st.button("Save"):
        if not notion_token or not notion_db_id:
            st.error("Set **NOTION_TOKEN** and **NOTION_DATABASE_ID** in your `.env` file.")
        elif not note or not note.strip():
            st.warning("Enter a note before saving.")
        else:
            ok, err = notion_create_daily_page(notion_token, notion_db_id, note.strip(), date.today())
            if ok:
                st.session_state["notion_saved_ok"] = True
                st.rerun()
            else:
                st.error(f"Notion API error: {err}")

    st.markdown("**Recent notes**")
    if not notion_token or not notion_db_id:
        st.caption("Configure `NOTION_TOKEN` and `NOTION_DATABASE_ID` in `.env`, and share the database with your integration.")
    else:
        recent, qerr = notion_query_recent_notes(notion_token, notion_db_id, limit=5)
        if qerr:
            st.warning(f"Could not load notes: {qerr}")
        elif not recent:
            st.caption("No rows yet — save a note above.")
        else:
            for d_s, text in recent:
                esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                st.markdown(
                    f"<span style='font-size: 0.8rem; color: #888;'>{d_s}</span> {esc}",
                    unsafe_allow_html=True,
                )


if __name__ == "__main__":
    main()
