import os
import io
import json
import datetime
import requests
import pandas as pd

# 1. Target Portal & Underlying Related File Direct URLs
DOC_ID = "18675f1d1639c7a34d463f59263ba0a2-0050012025"
BASE_URL = f"https://thedocs.worldbank.org/en/doc/{DOC_ID}"

PORTAL_URL = f"{BASE_URL}/"
MONTHLY_XLSX_URL = f"{BASE_URL}/related/CMO-Historical-Data-Monthly.xlsx"
ANNUAL_XLSX_URL = f"{BASE_URL}/related/CMO-Historical-Data-Annual.xlsx"
LATEST_PDF_URL = f"{BASE_URL}/related/CMO-Pink-Sheet-January-2026.pdf"

OUTPUT_JSON_PATH = "data/dashboard_data.json"

# 2. World Bank "Monthly Prices" Sheet Column Mapping (6 Native Commodities)
COLUMN_MAPPING = {
    "Gold": "Gold",
    "Aluminum": "Aluminium",
    "Copper": "Copper",
    "Tin": "Tin",
    "Rubber, TSR20": "Rubber",
    "Silver": "Silver"
}

def scrape_pink_sheet_monthly():
    print(f"Downloading underlying monthly Excel file: {MONTHLY_XLSX_URL}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(MONTHLY_XLSX_URL, headers=headers, timeout=60)
    resp.raise_for_status()

    # Read "Monthly Prices" worksheet (Row 5 contains headers, so skiprows=4)
    df = pd.read_excel(io.BytesIO(resp.content), sheet_name="Monthly Prices", skiprows=4)
    first_col = df.columns[0]
    df.rename(columns={first_col: "RawDate"}, inplace=True)

    # Filter out unit rows and empty rows; parse dates formatted as 2016M06
    df["DateObj"] = pd.to_datetime(df["RawDate"].astype(str), format="%YM%m", errors="coerce")
    df = df.dropna(subset=["DateObj"]).copy()

    # Match required commodity columns
    selected = {"DateObj": df["DateObj"]}
    for wb_col, target_col in COLUMN_MAPPING.items():
        matched = [c for c in df.columns if str(c).strip().startswith(wb_col)]
        if matched:
            selected[target_col] = pd.to_numeric(df[matched[0]], errors="coerce").round(2)

    out_df = pd.DataFrame(selected)
    out_df["Year"] = out_df["DateObj"].dt.year
    out_df["Month"] = out_df["DateObj"].dt.month

    # Time filtering & sampling rules: 2016-2023 Semi-Annual (June & Dec), 2024+ Monthly
    df_semi = out_df[(out_df["Year"] >= 2016) & (out_df["Year"] <= 2023) & (out_df["Month"].isin([6, 12]))]
    df_monthly = out_df[out_df["Year"] >= 2024]

    merged = pd.concat([df_semi, df_monthly], ignore_index=True).sort_values("DateObj")
    merged["Date"] = merged["DateObj"].dt.strftime("%Y-%m")
    merged.drop(columns=["DateObj", "Year", "Month"], inplace=True)
    return merged

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    final_df = scrape_pink_sheet_monthly()

    payload = {
        "metadata": {
            "document_id": DOC_ID,
            "source_portal": PORTAL_URL,
            "source_monthly_xlsx": MONTHLY_XLSX_URL,
            "source_annual_xlsx": ANNUAL_XLSX_URL,
            "source_latest_pdf": LATEST_PDF_URL,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "row_count": len(final_df)
        },
        "records": final_df.where(pd.notnull(final_df), None).to_dict(orient="records")
    }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Scraping completed! Exported {len(final_df)} records to {OUTPUT_JSON_PATH}")
