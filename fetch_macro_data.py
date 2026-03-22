#!/usr/bin/env python3
"""
Macro Dashboard - Fetch key US and Chile rates and print them to the terminal.

Uses only free data sources:
  - FRED (Federal Reserve Economic Data): free API key at https://fred.stlouisfed.org/docs/api/api_key.html
  - Banco Central de Chile (BCCh) API: free credentials at https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index.htm

Credentials (same pattern for both):
  - Set FRED_API_KEY and (for Chile) BCCH_USER + BCCH_PASS in your environment, OR
  - Create a .env file in this folder with:
      FRED_API_KEY=your_fred_key
      BCCH_USER=your_email@example.com
      BCCH_PASS=your_password
"""

import os
import sys

# ---------------------------------------------------------------------------
# Load credentials from environment or .env file (same pattern for FRED and BCCh)
# ---------------------------------------------------------------------------

def _load_env():
    """Load .env from script directory if present (no extra dependency)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", ".env")
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value and key not in os.environ:
                        os.environ[key] = value
    except FileNotFoundError:
        pass


def get_fred_api_key():
    """Get FRED API key from environment or .env file."""
    _load_env()
    key = os.environ.get("FRED_API_KEY")
    return key.strip() if key else None


def get_bcch_credentials():
    """Get BCCh API user and password from environment or .env file. Returns (user, pass) or (None, None)."""
    _load_env()
    user = os.environ.get("BCCH_USER")
    passwd = os.environ.get("BCCH_PASS")
    if user and passwd:
        return user.strip(), passwd.strip()
    return None, None


def get_notion_credentials():
    """
    Notion integration token and database ID from environment or .env.
    Returns (token, db_id) or (None, None).

    Tokens may start with ``secret_`` (older) or ``ntn_`` (newer); the value is used
    exactly as provided—only leading/trailing whitespace is removed, never the prefix.
    """
    _load_env()
    raw_token = os.environ.get("NOTION_TOKEN") or ""
    token = raw_token.strip() or None  # do not strip or rewrite token body (e.g. ntn_…)
    db_id = (os.environ.get("NOTION_DATABASE_ID") or "").strip() or None
    return token, db_id


# ---------------------------------------------------------------------------
# 1. FETCH US DATA FROM FRED (Federal Reserve)
# ---------------------------------------------------------------------------
# Series IDs from https://fred.stlouisfed.org
# You need a free API key: https://fred.stlouisfed.org/docs/api/api_key.html

FRED_SERIES = {
    "US Federal Funds Rate": "FEDFUNDS",       # Effective federal funds rate
    "US 2Y Treasury Yield": "DGS2",            # 2-year constant maturity
    "US 10Y Treasury Yield": "DGS10",          # 10-year constant maturity
    "US 30Y Treasury Yield": "DGS30",          # 30-year constant maturity
}


def _fred_value_at_or_before(series, target_date):
    """Return (value, date_str) for the latest observation on or before target_date, or (None, None)."""
    try:
        idx = series.index
        mask = idx <= target_date
        if not mask.any():
            return None, None
        i = series.loc[mask].index[-1]
        return float(series.loc[i]), str(i)[:10]
    except Exception:
        return None, None


def _fred_history(series, days=365):
    """Return list of (date_str, value) for the last `days` days (for spread sparklines)."""
    try:
        import pandas as pd

        if series is None or series.empty:
            return []
        cutoff = series.index[-1] - pd.Timedelta(days=days)
        sliced = series.loc[series.index >= cutoff].dropna()
        return [(str(idx)[:10], float(val)) for idx, val in sliced.items()]
    except Exception:
        return []


def fetch_fred_series(api_key):
    """
    Fetch FRED series with trend and 12m history.
    Returns dict label -> (cur_val, cur_date, val_1w, date_1w, val_1m, date_1m, history).
    """
    try:
        from fredapi import Fred
        import pandas as pd
    except ImportError:
        print("Missing dependency: run  pip install fredapi", file=sys.stderr)
        return None

    fred = Fred(api_key=api_key)
    result = {}

    for label, series_id in FRED_SERIES.items():
        try:
            series = fred.get_series(series_id)
            if series is None or series.empty:
                result[label] = (None, None, None, None, None, None, [])
                continue
            series = series.dropna()
            if series.empty:
                result[label] = (None, None, None, None, None, None, [])
                continue
            last_date = series.index[-1]
            last_value = float(series.iloc[-1])
            date_str = str(last_date)[:10] if last_date else None
            # Historical points for trend (1 week and 1 month before last observation)
            target_1w = last_date - pd.Timedelta(days=7)
            target_1m = last_date - pd.Timedelta(days=30)
            val_1w, date_1w = _fred_value_at_or_before(series, target_1w)
            val_1m, date_1m = _fred_value_at_or_before(series, target_1m)
            history = _fred_history(series, days=365)
            result[label] = (last_value, date_str, val_1w, date_1w, val_1m, date_1m, history)
        except Exception as e:
            result[label] = (None, str(e), None, None, None, None, [])

    return result


# ---------------------------------------------------------------------------
# 2. FETCH CHILE DATA FROM BANCO CENTRAL DE CHILE (BCCh) API
# ---------------------------------------------------------------------------
# API docs: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index.htm
# Series catalog: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/Webservices/series_EN.xlsx
# Credentials: free registration at the link above (user = email, pass = password).

BCCH_API_URL = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"

# Series codes from BCCh BDE catalog (from SearchSeries / series_EN.xlsx).
# TPM: official monetary policy rate; BCLP.TIS: secondary market yields for bonds in pesos (BCP).
BCCH_SERIES = {
    "Chile Central Bank Policy Rate (TPM)": "F022.TPM.TIN.D001.NO.Z.D",
    "Chile BCP/BTP 2Y Yield (CLP)": "F022.BCLP.TIS.AN02.NO.Z.D",
    "Chile BCP/BTP 5Y Yield (CLP)": "F022.BCLP.TIS.AN05.NO.Z.D",
    "Chile BCP/BTP 10Y Yield (CLP)": "F022.BCLP.TIS.AN10.NO.Z.D",
}


def _parse_bcch_response(data):
    """
    Parse BCCh GetSeries JSON. BCCh returns { "Series": [ { "Obs": [ {"indexDateString": "DD-MM-YYYY", "value": "x.xx", "statusCode": "OK"}, ... ] } ] }
    (R example from BCCh docs). Returns list of (date_str, value_float); skips observations with no data (NeuN/ND).
    """
    if not data:
        return []
    obs = data.get("Obs") or data.get("obs") or data.get("observations") or data.get("data") or []
    if not obs and data.get("Series") is not None:
        series = data["Series"]
        # Series can be a single object { "Obs": [...] } (e.g. R example: json_data$Series$Obs) or list [ { "Obs": [...] } ]
        if isinstance(series, dict):
            obs = series.get("Obs") or series.get("obs") or []
        elif isinstance(series, list) and len(series) > 0:
            obs = series[0].get("Obs") or series[0].get("obs") or []
    out = []
    for ob in obs:
        if not isinstance(ob, dict):
            if isinstance(ob, (list, tuple)) and len(ob) >= 2:
                try:
                    out.append((str(ob[0])[:10], float(ob[1])))
                except (TypeError, ValueError):
                    pass
            continue
        # BCCh uses indexDateString (e.g. "02-01-2015"); value can be "3" or "NeuN" when no data
        dt = ob.get("indexDateString") or ob.get("index") or ob.get("date") or ob.get("period")
        val = ob.get("value")
        if val is None or (isinstance(val, str) and val.strip().upper() in ("NEUN", "N/A", "")):
            continue
        if ob.get("statusCode") == "ND":
            continue
        if dt is None:
            continue
        # Normalize date: DD-MM-YYYY -> YYYY-MM-DD for sorting
        s = str(dt).strip()
        if len(s) >= 10 and s[2] in "-/" and s[5] in "-/":
            parts = s.replace("/", "-").split("-")
            if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
                s = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        else:
            s = s[:10]
        try:
            out.append((s, float(val)))
        except (TypeError, ValueError):
            pass
    return out


def _bcch_value_at_or_before(obs, target_ymd):
    """From sorted list of (date_str, value), return (value, date_str) for latest on or before target_ymd."""
    for d, v in reversed(obs):
        if d <= target_ymd:
            return round(v, 2), d
    return None, None


def fetch_bcch_series(user, password):
    """
    Fetch BCCh series with trend and 12m history.
    Returns dict label -> (cur_val, cur_date, val_1w, date_1w, val_1m, date_1m, history).
    """
    import urllib.request
    import urllib.parse
    import json
    from datetime import date, timedelta, datetime

    results = {}
    end = date.today()
    start = end - timedelta(days=365)
    firstdate = start.isoformat()
    lastdate = end.isoformat()

    for label, series_id in BCCH_SERIES.items():
        try:
            params = {
                "user": user,
                "pass": password,
                "function": "GetSeries",
                "timeseries": series_id,
                "firstdate": firstdate,
                "lastdate": lastdate,
            }
            url = BCCH_API_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("Codigo") and data.get("Codigo") != 0:
                msg = data.get("Descripcion", "Unknown error")
                results[label] = (None, msg, None, None, None, None, [])
                continue
            obs = _parse_bcch_response(data)
            if not obs and isinstance(data, dict):
                for key in ("Obs", "observations", "data", "values"):
                    obs = _parse_bcch_response({key: data.get(key)})
                    if obs:
                        break
            if not obs:
                results[label] = (None, "No observations in response", None, None, None, None, [])
                continue
            obs.sort(key=lambda x: x[0])
            last_date_str, last_val = obs[-1]
            cur = round(last_val, 2)
            target_1w = (datetime.strptime(last_date_str, "%Y-%m-%d").date() - timedelta(days=7)).strftime("%Y-%m-%d")
            target_1m = (datetime.strptime(last_date_str, "%Y-%m-%d").date() - timedelta(days=30)).strftime("%Y-%m-%d")
            val_1w, date_1w = _bcch_value_at_or_before(obs, target_1w)
            val_1m, date_1m = _bcch_value_at_or_before(obs, target_1m)
            cutoff_ymd = (datetime.strptime(last_date_str, "%Y-%m-%d").date() - timedelta(days=365)).strftime("%Y-%m-%d")
            history = [(d, float(v)) for d, v in obs if d >= cutoff_ymd]
            results[label] = (cur, last_date_str, val_1w, date_1w, val_1m, date_1m, history)
        except urllib.error.HTTPError as e:
            results[label] = (None, f"HTTP {e.code}", None, None, None, None, [])
        except urllib.error.URLError as e:
            results[label] = (None, str(e.reason) if getattr(e, "reason", None) else str(e), None, None, None, None, [])
        except json.JSONDecodeError as e:
            results[label] = (None, f"Invalid JSON: {e}", None, None, None, None, [])
        except Exception as e:
            results[label] = (None, str(e), None, None, None, None, [])

    return results


# ---------------------------------------------------------------------------
# 3. SPREAD CALCULATIONS
# ---------------------------------------------------------------------------

def _spread_date_recent(d1, d2):
    """Return the more recent of two date strings (YYYY-MM-DD); used as observation date for the spread."""
    if not d1:
        return d2
    if not d2:
        return d1
    return max(d1, d2)


def _cur(r):
    """Current value and date from a rate result (first two fields of 6- or 7-tuple)."""
    if not r or len(r) < 2:
        return None, None
    return r[0], r[1]


def compute_2y10y_spread(fred_results):
    """Compute US 2Y/10Y spread (10Y - 2Y) from FRED results. Return (spread, date) or (None, msg)."""
    two_y = fred_results.get("US 2Y Treasury Yield")
    ten_y = fred_results.get("US 10Y Treasury Yield")
    if not two_y or not ten_y:
        return None, "Missing 2Y or 10Y"
    v2, d2 = _cur(two_y)
    v10, d10 = _cur(ten_y)
    if v2 is None or v10 is None:
        return None, "Missing 2Y or 10Y values"
    spread = round(v10 - v2, 2)
    date_str = _spread_date_recent(d10, d2)
    return spread, date_str


def compute_all_spreads(fred_results, bcch_results):
    """
    Compute all dashboard spreads. Returns list of (label, spread_value, date_str).
    Uses current value (first element) from each rate result.
    """
    spreads = []
    us_2y = fred_results.get("US 2Y Treasury Yield") if fred_results else None
    us_10y = fred_results.get("US 10Y Treasury Yield") if fred_results else None
    cl_2y = bcch_results.get("Chile BCP/BTP 2Y Yield (CLP)") if bcch_results else None
    cl_10y = bcch_results.get("Chile BCP/BTP 10Y Yield (CLP)") if bcch_results else None

    v2, d2 = _cur(us_2y)
    v10, d10 = _cur(us_10y)

    if us_2y and us_10y and v2 is not None and v10 is not None:
        spreads.append(("US 2Y/10Y spread (10Y - 2Y)", round(v10 - v2, 2), _spread_date_recent(d10, d2)))
    else:
        spreads.append(("US 2Y/10Y spread (10Y - 2Y)", None, "N/A"))

    c10, dc10 = _cur(cl_10y)
    if cl_10y and us_10y and c10 is not None and v10 is not None:
        spreads.append(("Chile 10Y vs US 10Y sovereign spread", round(c10 - v10, 2), _spread_date_recent(dc10, d10)))
    else:
        spreads.append(("Chile 10Y vs US 10Y sovereign spread", None, "N/A"))

    c2, dc2 = _cur(cl_2y)
    if cl_2y and us_2y and c2 is not None and v2 is not None:
        spreads.append(("Chile 2Y vs US 2Y spread", round(c2 - v2, 2), _spread_date_recent(dc2, d2)))
    else:
        spreads.append(("Chile 2Y vs US 2Y spread", None, "N/A"))

    if cl_10y and cl_2y and c10 is not None and c2 is not None:
        spreads.append(("Chile yield curve spread (10Y - 2Y)", round(c10 - c2, 2), _spread_date_recent(dc10, dc2)))
    else:
        spreads.append(("Chile yield curve spread (10Y - 2Y)", None, "N/A"))

    return spreads


# ---------------------------------------------------------------------------
# 4. PRINT A CLEAN TABLE TO THE TERMINAL
# ---------------------------------------------------------------------------

def print_report(fred_results, bcch_results, spreads):
    """Print a simple, readable table of all series. spreads: list of (label, value, date)."""
    width = 50
    sep = "=" * width
    print()
    print(sep)
    print("  MACRO RATES DASHBOARD")
    print("  (as of latest available data)")
    print(sep)

    # US rates from FRED (row: cur_val, cur_date, ...)
    print("\n  --- UNITED STATES (FRED) ---\n")
    for label, row in (fred_results or {}).items():
        value, date_or_err = row[0], row[1] if len(row) >= 2 else None
        if value is not None:
            print(f"  {label:<40} {value:>6.2f}%    ({date_or_err or 'N/A'})")
        else:
            print(f"  {label:<40}  ---     ({date_or_err or 'N/A'})")

    # Chile (all from BCCh)
    print("\n  --- CHILE (BCCh) ---\n")
    for label, row in (bcch_results or {}).items():
        value, date_or_err = row[0], row[1] if len(row) >= 2 else None
        if value is not None:
            print(f"  {label:<40} {value:>6.2f}%    ({date_or_err or 'N/A'})")
        else:
            print(f"  {label:<40}  ---     ({date_or_err or 'N/A'})")

    # Spreads (calculated)
    print("\n  --- SPREADS ---\n")
    for label, value, date_str in (spreads or []):
        if value is not None:
            print(f"  {label:<40} {value:>+6.2f}%    ({date_str or 'N/A'})")
        else:
            print(f"  {label:<40}  ---     ({date_str or 'N/A'})")

    print()
    print(sep)
    print()


def main():
    # Check FRED API key
    api_key = get_fred_api_key()
    if not api_key:
        print(
            "FRED API key not found. Set FRED_API_KEY in your environment, or create a .env file with:\n  FRED_API_KEY=your_key\n"
            "Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check BCCh credentials (same pattern: env or .env)
    bcch_user, bcch_pass = get_bcch_credentials()
    if not bcch_user or not bcch_pass:
        print(
            "BCCh credentials not found. Set BCCH_USER and BCCH_PASS in your environment, or add to .env:\n"
            "  BCCH_USER=your_email@example.com\n  BCCH_PASS=your_password\n"
            "Free registration: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index.htm",
            file=sys.stderr,
        )
        sys.exit(1)

    # Fetch all data
    fred_results = fetch_fred_series(api_key)
    bcch_results = fetch_bcch_series(bcch_user, bcch_pass)
    spreads = compute_all_spreads(fred_results or {}, bcch_results or {})

    # Print report
    print_report(fred_results, bcch_results, spreads)


if __name__ == "__main__":
    main()
