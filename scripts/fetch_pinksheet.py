import os
import io
import re
import json
import datetime
import requests
import pandas as pd

# 1. Target URLs
LBMA_PORTAL_URL = "https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices"
DEFAULT_LBMA_GOLD_URL = "https://prices.lbma.org.uk/json/gold_pm.json"
DEFAULT_LBMA_SILVER_URL = "https://prices.lbma.org.uk/json/silver.json"

DOC_ID_2026 = "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026"
DOC_ID_2025 = "18675f1d1639c7a34d463f59263ba0a2-0050012025"

OUTPUT_JSON_PATH = "data/dashboard_data.json"

COLUMN_MAPPING = {
    "Gold": "Gold",
    "Aluminum": "Aluminium",
    "Copper": "Copper",
    "Tin": "Tin",
    "Rubber, TSR20": "Rubber",
    "Silver": "Silver"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": LBMA_PORTAL_URL
}

def scrape_lbma_portal_endpoints():
    """Directly request https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices and discover feed endpoints."""
    gold_url = DEFAULT_LBMA_GOLD_URL
    silver_url = DEFAULT_LBMA_SILVER_URL
    status_str = "Connected"
    try:
        print(f"Scraping LBMA Precious Metal Prices page: {LBMA_PORTAL_URL}")
        resp = requests.get(LBMA_PORTAL_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html_text = resp.text
        status_str = f"HTTP {resp.status_code} ({len(html_text)} bytes)"

        found_gold = re.findall(r"https://prices\.lbma\.org\.uk/json/gold_pm\.json", html_text)
        found_silver = re.findall(r"https://prices\.lbma\.org\.uk/json/silver\.json", html_text)
        if found_gold:
            gold_url = found_gold[0]
        if found_silver:
            silver_url = found_silver[0]
    except Exception as e:
        print(f"Note: Direct HTML inspection of {LBMA_PORTAL_URL} returned: {e}")
        status_str = "Direct Feed Mode"
    return gold_url, silver_url, status_str

def fetch_lbma_monthly_series(json_url, col_name, decimals=2):
    """Fetch daily USD auction prices from LBMA feed and aggregate into monthly averages."""
    try:
        print(f"Fetching LBMA data stream from: {json_url}")
        resp = requests.get(json_url, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        records = resp.json()
        rows = list()
        for entry in records:
            d_str = entry.get("d")
            vals = entry.get("v")
            if d_str and isinstance(vals, list) and len(vals) > 0 and vals[0] is not None:
                usd_val = float(vals[0])
                if usd_val > 0:
                    rows.append({"DateStr": str(d_str)[:7], col_name: usd_val})
        if not rows:
            return pd.DataFrame(columns=["Date", col_name])
        df_lbma = pd.DataFrame(rows)
        df_monthly = df_lbma.groupby("DateStr", as_index=False)[col_name].mean()
        df_monthly[col_name] = df_monthly[col_name].round(decimals)
        df_monthly.rename(columns={"DateStr": "Date"}, inplace=True)
        return df_monthly
    except Exception as e:
        print(f"Warning: LBMA fetch failed for {col_name}: {e}")
        return pd.DataFrame(columns=["Date", col_name])

def download_pinksheet_excel():
    for doc_id in (DOC_ID_2026, DOC_ID_2025):
        base_url = f"https://thedocs.worldbank.org/en/doc/{doc_id}"
        xlsx_url = f"{base_url}/related/CMO-Historical-Data-Monthly.xlsx"
        try:
            print(f"Trying World Bank Pink Sheet Excel: {xlsx_url}")
            resp = requests.get(xlsx_url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp.content, doc_id, base_url
        except Exception as e:
            print(f"Warning: World Bank container {doc_id} unavailable: {e}")
    raise RuntimeError("Could not download World Bank Pink Sheet Excel file.")

def filter_semi_annual_and_monthly(df):
    df["Year"] = df["Date"].str.slice(0, 4).astype(int)
    df["Month"] = df["Date"].str.slice(5, 7).astype(int)
    semi_mask = (df["Year"] >= 2016) & (df["Year"] <= 2023) & (df["Month"].isin((6, 12)))
    monthly_mask = df["Year"] >= 2024
    filtered = df[semi_mask | monthly_mask].copy()
    filtered.sort_values("Date", inplace=True)
    filtered.drop(columns=["Year", "Month"], inplace=True)
    return filtered

def build_combined_dataset():
    gold_url, silver_url, lbma_status = scrape_lbma_portal_endpoints()
    content, active_doc_id, base_url = download_pinksheet_excel()

    df = pd.read_excel(io.BytesIO(content), sheet_name="Monthly Prices", skiprows=4)
    first_col = df.columns[0]
    df.rename(columns={first_col: "RawDate"}, inplace=True)

    df["DateObj"] = pd.to_datetime(df["RawDate"].astype(str), format="%YM%m", errors="coerce")
    df = df.dropna(subset=["DateObj"]).copy()
    df["Date"] = df["DateObj"].dt.strftime("%Y-%m")

    selected = {"Date": df["Date"]}
    for wb_col, target_col in COLUMN_MAPPING.items():
        matched = [c for c in df.columns if str(c).strip().startswith(wb_col)]
        if matched:
            decimals = 0 if target_col in ("Gold", "Aluminium", "Copper", "Tin") else 2
            selected[target_col] = pd.to_numeric(df[matched[0]], errors="coerce").round(decimals)

    wb_df = pd.DataFrame(selected)

    lbma_gold = fetch_lbma_monthly_series(gold_url, "Gold_LBMA", decimals=0)
    lbma_silver = fetch_lbma_monthly_series(silver_url, "Silver_LBMA", decimals=2)

    merged = pd.merge(wb_df, lbma_gold, on="Date", how="outer")
    merged = pd.merge(merged, lbma_silver, on="Date", how="outer")

    if "Gold_LBMA" in merged.columns:
        merged["Gold"] = merged["Gold_LBMA"].combine_first(merged.get("Gold"))
        merged.drop(columns=["Gold_LBMA"], inplace=True)
    if "Silver_LBMA" in merged.columns:
        merged["Silver"] = merged["Silver_LBMA"].combine_first(merged.get("Silver"))
        merged.drop(columns=["Silver_LBMA"], inplace=True)

    final_df = filter_semi_annual_and_monthly(merged)
    return final_df, active_doc_id, base_url, gold_url, silver_url, lbma_status

def main():
    os.makedirs("data", exist_ok=True)
    final_df, active_doc_id, base_url, gold_url, silver_url, lbma_status = build_combined_dataset()

    payload = {
        "metadata": {
            "document_id": active_doc_id,
            "lbma_portal": LBMA_PORTAL_URL,
            "lbma_status": lbma_status,
            "lbma_gold_feed": gold_url,
            "lbma_silver_feed": silver_url,
            "source_portal": f"{base_url}/",
            "source_monthly_xlsx": f"{base_url}/related/CMO-Historical-Data-Monthly.xlsx",
            "source_latest_pdf": f"{base_url}/related/CMO-Pink-Sheet-October-2026.pdf",
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "row_count": len(final_df)
        },
        "records": final_df.where(pd.notnull(final_df), None).to_dict(orient="records")
    }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Scraping completed! Saved {len(final_df)} records to {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
