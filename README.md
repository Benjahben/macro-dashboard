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

   **Example `.env` file:**
   ```
   FRED_API_KEY=your_fred_key
   BCCH_USER=your_email@example.com
   BCCH_PASS=your_password
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
Opens in your browser at http://localhost:8501. Same data as the terminal script, with metric cards, spread coloring (green/red), and a Refresh button.

## Chile series codes (BCCh)

Chile data comes from the Banco Central de Chile (BCCh) Statistics Database API. The script uses these series codes (from the official BDE catalog):

- **TPM (monetary policy rate):** `F022.TPM.TIN.D001.NO.Z.D`
- **BCP/BTP 2Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN02.NO.Z.D`
- **BCP/BTP 5Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN05.NO.Z.D`
- **BCP/BTP 10Y yield (CLP), secondary market:** `F022.BCLP.TIS.AN10.NO.Z.D`

To discover more series, run `python list_bcch_series.py` (uses the same `.env` credentials); it prints DAILY/MONTHLY series matching TPM, bonds, yields, etc. Full catalog: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/Webservices/series_EN.xlsx
