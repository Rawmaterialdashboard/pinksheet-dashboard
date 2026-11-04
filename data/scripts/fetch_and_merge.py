import os
import io
import json
import datetime
import requests
import pandas as pd

# 1. 目标页面与底层关联文件直链（基于 thedocs.worldbank.org 18675f1d1639c7a34d463f59263ba0a2-0050012025）
DOC_ID = "18675f1d1639c7a34d463f59263ba0a2-0050012025"
BASE_URL = f"https://thedocs.worldbank.org/en/doc/{DOC_ID}"

PORTAL_URL = f"{BASE_URL}/world-bank-commodities-price-data-the-pink-sheet"
MONTHLY_XLSX_URL = f"{BASE_URL}/related/CMO-Historical-Data-Monthly.xlsx"
ANNUAL_XLSX_URL = f"{BASE_URL}/related/CMO-Historical-Data-Annual.xlsx"
LATEST_PDF_URL = f"{BASE_URL}/related/CMO-Pink-Sheet-January-2026.pdf"

MANUAL_CSV_PATH = "data/manual_metrics.csv"
OUTPUT_JSON_PATH = "data/dashboard_data.json"

# Monthly Prices 表头字段映射
COLUMN_MAPPING = {
    "Gold": "Gold",
    "Aluminum": "Aluminium",
    "Copper": "Copper",
    "Tin": "Tin",
    "Rubber, TSR20": "Rubber",
    "Silver": "Silver"
}

def scrape_pink_sheet_monthly():
    print(f"正在抓取底层月度 Excel 文件: {MONTHLY_XLSX_URL}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(MONTHLY_XLSX_URL, headers=headers, timeout=60)
    resp.raise_for_status()

    # 读取 Monthly Prices 工作表（第 5 行为列名，即 index=4）
    df = pd.read_excel(io.BytesIO(resp.content), sheet_name="Monthly Prices", skiprows=4)
    df.rename(columns={df.columns[0]: "RawDate"}, inplace=True)

    # 过滤掉单位行（第 6 行）和空行，解析类似 2016M06 的日期格式
    df["DateObj"] = pd.to_datetime(df["RawDate"].astype(str), format="%YM%m", errors="coerce")
    df = df.dropna(subset=["DateObj"]).copy()

    # 匹配所需商品列
    selected = {"DateObj": df["DateObj"]}
    for wb_col, target_col in COLUMN_MAPPING.items():
        matched = [c for c in df.columns if str(c).strip().startswith(wb_col)]
        if matched:
            selected[target_col] = pd.to_numeric(df[matched[0]], errors="coerce").round(2)

    out_df = pd.DataFrame(selected)
    out_df["Year"] = out_df["DateObj"].dt.year
    out_df["Month"] = out_df["DateObj"].dt.month

    # 时间过滤与采样规则：2016-2023 半年度(6月,12月)，2024+ 月度
    df_semi = out_df[(out_df["Year"] >= 2016) & (out_df["Year"] <= 2023) & (out_df["Month"].isin())]
    df_monthly = out_df[out_df["Year"] >= 2024]

    merged = pd.concat([df_semi, df_monthly], ignore_index=True).sort_values("DateObj")
    merged["Date"] = merged["DateObj"].dt.strftime("%Y-%m")
    merged.drop(columns=["DateObj", "Year", "Month"], inplace=True)
    return merged

def merge_with_supplement(df_wb):
    if os.path.exists(MANUAL_CSV_PATH):
        sup = pd.read_csv(MANUAL_CSV_PATH)
        sup["Date"] = sup["Date"].astype(str).str.strip()
        df_wb = pd.merge(df_wb, sup, on="Date", how="left")
    else:
        df_wb["Tungsten"] = None
        df_wb["Steel"] = None
    return df_wb

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    wb_df = scrape_pink_sheet_monthly()
    final_df = merge_with_supplement(wb_df)

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

    print(f"抓取完成！共输出 {len(final_df)} 条记录至 {OUTPUT_JSON_PATH}")
