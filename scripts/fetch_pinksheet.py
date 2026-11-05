import os
import io
import json
import datetime
import requests
import pandas as pd

# 1. Target 2026 World Bank Pink Sheet Container (with 2025 fallback)
DOC_ID_2026 = "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026"
DOC_ID_2025 = "18675f1d1639c7a34d463f59263ba0a2-0050012025"

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

def download_pinksheet_excel():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    for doc_id in [DOC_ID_2026, DOC_ID_2025]:
        base_url = f"https://thedocs.worldbank.org/en/doc/{doc_id}"
        xlsx_url = f"{base_url}/related/CMO-Historical-Data-Monthly.xlsx"
        try:
            print(f"Trying to download monthly Excel file from: {xlsx_url}")
            resp = requests.get(xlsx_url, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.content, doc_id, base_url
        except Exception as e:
            print(f"Warning: Failed for {doc_id}: {e}")
    raise RuntimeError("Could not download World Bank Pink Sheet Excel file from any container.")

def scrape_pink_sheet_monthly():
    content, active_doc_id, base_url = download_pinksheet_excel()

    # Read "Monthly Prices" worksheet (Row 5 contains headers, so skiprows=4)
    df = pd.read_excel(io.BytesIO(content), sheet_name="Monthly Prices", skiprows=4)
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
    df_semi = out_df[(out_df["Year"] >= 2016) & (out_df["Year"] <= 2023) & (out_df["Month"].isin())]
    df_monthly = out_df[out_df["Year"] >= 2024]

    merged = pd.concat([df_semi, df_monthly], ignore_index=True).sort_values("DateObj")
    merged["Date"] = merged["DateObj"].dt.strftime("%Y-%m")
    merged.drop(columns=["DateObj", "Year", "Month"], inplace=True)
    return merged, active_doc_id, base_url

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    final_df, active_doc_id, base_url = scrape_pink_sheet_monthly()

    payload = {
        "metadata": {
            "document_id": active_doc_id,
            "source_portal": f"{base_url}/",
            "source_monthly_xlsx": f"{base_url}/related/CMO-Historical-Data-Monthly.xlsx",
            "source_annual_xlsx": f"{base_url}/related/CMO-Historical-Data-Annual.xlsx",
            "source_latest_pdf": f"{base_url}/related/CMO-Pink-Sheet-October-2026.pdf",
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "row_count": len(final_df)
        },
        "records": final_df.where(pd.notnull(final_df), None).to_dict(orient="records")
    }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Scraping completed! Exported {len(final_df)} records to {OUTPUT_JSON_PATH}")
