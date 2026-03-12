#!/usr/bin/env python3
"""
Discover BCCh (Banco Central de Chile) series codes for TPM and bond yields.
Uses the same credentials as fetch_macro_data.py (.env: BCCH_USER, BCCH_PASS).
Run: python list_bcch_series.py
Prints series that match: TPM, policy rate, bond, BTP, BCP, yield, 2y, 5y, 10y.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

# Reuse credential loading from main script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_macro_data import get_bcch_credentials, BCCH_API_URL, _load_env

KEYWORDS = [
    "tpm", "policy", "monetary", "tasa politica",
    "bono", "bond", "btp", "bcp", "bonos",
    "yield", "rendimiento", "tasa",
    "2 year", "5 year", "10 year", "2 años", "5 años", "10 años",
    "secondary", "secundario", "pesos", "clp",
]


def search_series(user, password, frequency):
    """Call BCCh SearchSeries API. Returns list of { seriesId, frequencyCode, englishTitle, spanishTitle }. """
    params = {
        "user": user,
        "pass": password,
        "function": "SearchSeries",
        "frequency": frequency,
    }
    url = BCCH_API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    infos = data.get("SeriesInfos") or data.get("seriesInfos") or []
    return infos if isinstance(infos, list) else []


def matches(series_id, english_title, spanish_title):
    text = " ".join(
        str(x).lower() for x in (series_id or "", english_title or "", spanish_title or "")
    )
    return any(kw in text for kw in KEYWORDS)


def main():
    _load_env()
    user, password = get_bcch_credentials()
    if not user or not password:
        print("Set BCCH_USER and BCCH_PASS in .env (same as fetch_macro_data.py)", file=sys.stderr)
        sys.exit(1)

    seen = set()
    for freq in ("DAILY", "MONTHLY"):
        print(f"\n--- {freq} ---\n", file=sys.stderr)
        try:
            infos = search_series(user, password, freq)
        except Exception as e:
            print(f"SearchSeries {freq} failed: {e}", file=sys.stderr)
            continue
        for item in infos:
            sid = item.get("seriesId") or item.get("seriesID")
            en = item.get("englishTitle") or ""
            es = item.get("spanishTitle") or ""
            if not sid or sid in seen:
                continue
            if not matches(sid, en, es):
                continue
            seen.add(sid)
            print(sid)
            print(f"  EN: {en}")
            print(f"  ES: {es}")
            print()


if __name__ == "__main__":
    main()
