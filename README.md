# Macro Rates Dashboard

Fetches key US and Chile rates and prints them in the terminal. Uses **free** data sources only.

## Data shown

| Series | Source |
|--------|--------|
| US Federal Funds Rate | FRED |
| US 2Y, 10Y, 30Y Treasury yields | FRED |
| US 2Y/10Y spread (10Y − 2Y) | Calculated |
| Chile Central Bank policy rate (TPM) | BCCh API |
| Chile BCP/BTP 2Y, 5Y, 10Y yields (CLP) | BCCh API |

## Setup

1. **Python 3**  
   Make sure Python 3 is installed (`python3 --version`).

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   (Only `fredapi` is required; BCCh is called with Python’s built-in `urllib`.)

3. **Credentials (same pattern for both)**

   You can set them in the **environment** or in a **`.env` file** in this folder.

   **FRED** (free API key):
   - Get a key at: https://fred.stlouisfed.org/docs/api/api_key.html  
   - `FRED_API_KEY=your_key_here`

   **BCCh** (free registration):
   - Register at: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index.htm  
   - Use your email and password as:
   - `BCCH_USER=your_email@example.com`
   - `BCCH_PASS=your_password`

   **Notion** (optional — for Daily View in the Streamlit app):
   - Create an [integration](https://www.notion.so/my-integrations), copy the **internal integration token** as `NOTION_TOKEN` (may start with `ntn_` or `secret_`; paste it exactly—nothing in the app rewrites these prefixes).
   - Create or pick a **database** with properties named exactly **`Date`** (type *Date*) and **`Note`** (type *Text*). Copy the database ID from the URL (32 hex characters, with or without hyphens) as `NOTION_DATABASE_ID`.
   - In Notion, open the database → **⋯** → **Connections** (or *Add connections*) → connect your integration so it can read/write the database.
   - If the API rejects the payload, your **Note** column might be Notion’s primary **Title** type (even if labeled “Note”): add `NOTION_NOTE_AS_TITLE=true` to `.env`.

   **Example `.env` file:**
   ```
   FRED_API_KEY=your_fred_key
   BCCH_USER=your_email@example.com
   BCCH_PASS=your_password
   # NOTION_TOKEN: paste full value from Notion (starts with ntn_ or secret_)
   NOTION_TOKEN=your_notion_integration_token
   NOTION_DATABASE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

   **Or export in the shell:**
   ```bash
   export FRED_API_KEY=your_key
   export BCCH_USER=your_email@example.com
   export BCCH_PASS=your_password
   ```

## Run

**Terminal (table output):**
```bash
python fetch_macro_data.py
```

**Web dashboard (Streamlit):**
```bash
pip install -r requirements.txt   # includes streamlit
streamlit run dashboard.py
```
Opens in your browser at http://localhost:8501. Same data as the terminal script, plus:

- Metric cards with 1w / 1m trends and Fed / TPM meeting hints
- Yield curve chart (US vs Chile, current vs 1w ago) via Plotly
- **Spreads:** green/red headline values and **~12m sparklines** under each (dotted **12m average** line + label; line color follows spread sign)
- Anomaly banner (alerts vs 4% warning)
- **Daily View:** save notes to a **Notion** database (`Date` + `Note` columns) and list the **five most recent** rows (sorted by date)

BCCh pulls **~365 days** of history for trends and Chile sparklines; FRED series keep full history but sparklines use the last **365 days** of points.

## Chile series codes (BCCh)

Chile data comes from the Banco Central de Chile (BCCh) Statistics Database API. The script uses these series codes (from the official BDE catalog):

- **TPM (monetary policy rate):** `F022.TPM.TIN.D001.NO.Z.D`
- **BCP/BTP 2Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN02.NO.Z.D`
- **BCP/BTP 5Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN05.NO.Z.D`
- **BCP/BTP 10Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN10.NO.Z.D`

To discover more series, run `python list_bcch_series.py` (uses the same `.env` credentials); it prints DAILY/MONTHLY series matching TPM, bonds, yields, etc. Full catalog: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/Webservices/series_EN.xlsx
