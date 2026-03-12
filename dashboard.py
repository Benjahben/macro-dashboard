"""
Macro Rates Dashboard - Streamlit web app.
Uses the same data logic as fetch_macro_data.py. Run: streamlit run dashboard.py
"""

import streamlit as st

from fetch_macro_data import (
    get_fred_api_key,
    get_bcch_credentials,
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
):
    """Render a rate metric: value, bps vs 1m (gray, ⚠ if |change|>10bps), direction arrow (red/green), date."""
    with st.container():
        st.markdown(f"**{label}**")
        if cur is None:
            st.markdown("<span style='font-size: 1.75rem; font-weight: 600;'>—</span>", unsafe_allow_html=True)
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
            metric_card_with_trend(label, cur, cur_date, val_1w, date_1w, val_1m, date_1m)

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
            metric_card_with_trend(label, cur, cur_date, val_1w, date_1w, val_1m, date_1m)

    st.divider()

    # --- Spreads (color coded) ---
    st.subheader("Spreads")
    spread_cols = st.columns(4)
    for i, (label, value, date_str) in enumerate(spreads):
        with spread_cols[i]:
            metric_card(label, value, date_str or "N/A", is_spread=True)


if __name__ == "__main__":
    main()
