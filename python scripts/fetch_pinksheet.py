import os
import io
import re
import json
import datetime
import requests
import pandas as pd

# 1. Official Target URLs
LBMA_PORTAL_URL = "https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices"
DEFAULT_LBMA_GOLD_URL = "https://prices.lbma.org.uk/json/gold_pm.json"
DEFAULT_LBMA_SILVER_URL = "https://prices.lbma.org.uk/json/silver.json"
DEFAULT_LBMA_PLATINUM_URL = "https://prices.lbma.org.uk/json/platinum_pm.json"

STEEL_EHP_URL = "https://www.e-h-p.de/zuschlaege/"
STEEL_EINSAL_DE_URL = "https://einsal.com/tools/energie-schrott-legierungszuschlag"
CHINATUNGSTEN_URL = "http://news.chinatungsten.com/cn/tungsten-jewelry-news/20-tungsten-news-cn/tungsten-product-news/174387-tpn-15074.html"

DOC_ID_2026 = "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026"
DOC_ID_2025 = "18675f1d1639c7a34d463f59263ba0a2-0050012025"

OUTPUT_JSON_PATH = "data/dashboard_data.json"

COLUMN_MAPPING = {
    "Gold": "Gold",
    "Aluminum": "Aluminium",
    "Copper": "Copper",
    "Tin": "Tin",
    "Rubber, TSR20": "Rubber",
    "Silver": "Silver",
    "Platinum": "Platinum"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": LBMA_PORTAL_URL
}

MONTH_GERMAN_MAP = {
    "januar": "01", "februar": "02", "märz": "03", "maerz": "03",
    "april": "04", "mai": "05", "juni": "06", "juli": "07",
    "august": "08", "september": "09", "oktober": "10", "november": "11", "dezember": "12"
}

def scrape_lbma_portal_endpoints():
    """Directly request https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices for Gold, Silver & Platinum."""
    gold_url = DEFAULT_LBMA_GOLD_URL
    silver_url = DEFAULT_LBMA_SILVER_URL
    platinum_url = DEFAULT_LBMA_PLATINUM_URL
    status_str = "Connected"
    try:
        print(f"Scraping LBMA Precious Metal Prices page: {LBMA_PORTAL_URL}")
        resp = requests.get(LBMA_PORTAL_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html_text = resp.text
        status_str = f"HTTP {resp.status_code} ({len(html_text)} bytes)"
    except Exception as e:
        print(f"Note: Direct HTML inspection of {LBMA_PORTAL_URL} returned: {e}")
        status_str = "Direct Feed Mode"
    return gold_url, silver_url, platinum_url, status_str

def fetch_lbma_monthly_series(json_url, col_name, decimals=2, extract_fx=False):
    """Fetch daily USD (and EUR for FX) auction prices from LBMA feed and aggregate into monthly averages."""
    try:
        print(f"Fetching LBMA stream ({col_name}) from: {json_url}")
        resp = requests.get(json_url, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        records = resp.json()
        rows = list()
        for entry in records:
            d_str = entry.get("d")
            vals = entry.get("v")
            if d_str and isinstance(vals, list) and len(vals) > 0:
                it = iter(vals)
                usd_raw = next(it, None)
                gbp_raw = next(it, None)
                eur_raw = next(it, None)
                if usd_raw is not None:
                    usd_val = float(usd_raw)
                    if usd_val > 0:
                        item = {"DateStr": str(d_str)[:7], col_name: usd_val}
                        if extract_fx and eur_raw is not None and float(eur_raw) > 0:
                            item["EurUsd"] = usd_val / float(eur_raw)
                        rows.append(item)
        if not rows:
            cols = list(("Date", col_name, "EurUsd")) if extract_fx else list(("Date", col_name))
            return pd.DataFrame(columns=cols)
        df_lbma = pd.DataFrame(rows)
        agg_cols = list((col_name, "EurUsd")) if (extract_fx and "EurUsd" in df_lbma.columns) else list((col_name,))
        df_monthly = df_lbma.groupby("DateStr", as_index=False)[agg_cols].mean()
        df_monthly[col_name] = df_monthly[col_name].round(decimals)
        if "EurUsd" in df_monthly.columns:
            df_monthly["EurUsd"] = df_monthly["EurUsd"].round(4)
        df_monthly.rename(columns={"DateStr": "Date"}, inplace=True)
        return df_monthly
    except Exception as e:
        print(f"Warning: LBMA fetch failed for {col_name}: {e}")
        cols = list(("Date", col_name, "EurUsd")) if extract_fx else list(("Date", col_name))
        return pd.DataFrame(columns=cols)

def scrape_steel_14057_surcharges():
    """
    Scrape monthly 1.4057 alloy surcharges (€/kg) from:
    1) Walzwerke Einsal German official archive (https://einsal.com/tools/energie-schrott-legierungszuschlag)
    2) EHP Edelstahl official table (https://www.e-h-p.de/zuschlaege/)
    """
    rows = list()

    try:
        print(f"Scraping 1.4057 archive from Walzwerke Einsal DE: {STEEL_EINSAL_DE_URL}")
        resp = requests.get(STEEL_EINSAL_DE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        clean_text = re.sub(r"<[^>]+>", " ", resp.text)
        clean_text = re.sub(r"\s+", " ", clean_text)
        row_pattern = r"(\d{2})\.(\d{4})\s+\d+[,\.]\d{2}\s+(\d+[,\.]\d{2})\s+\d+[,\.]\d{2}\s+\d+[,\.]\d{2}"
        for m_str, y_str, val_14057 in re.findall(row_pattern, clean_text):
            date_key = f"{y_str}-{m_str}"
            val_float = round(float(val_14057.replace(",", ".")), 2)
            rows.append({"Date": date_key, "Steel14057": val_float})
    except Exception as e:
        print(f"Warning: Walzwerke Einsal DE scrape returned: {e}")

    try:
        print(f"Scraping current 1.4057 surcharge from EHP Edelstahl: {STEEL_EHP_URL}")
        resp2 = requests.get(STEEL_EHP_URL, headers=HEADERS, timeout=30)
        resp2.raise_for_status()
        clean_ehp = re.sub(r"<[^>]+>", " ", resp2.text)
        clean_ehp = re.sub(r"\s+", " ", clean_ehp)

        header_match = re.search(r"Legierungszuschl[aä]ge\s*\|\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})", clean_ehp)
        ehp_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        if header_match:
            m_name = header_match.group(1).strip().lower()
            y_val = header_match.group(2).strip()
            m_num = MONTH_GERMAN_MAP.get(m_name)
            if m_num:
                ehp_date = f"{y_val}-{m_num}"

        grade_match = re.search(r"1\.4057\s+(\d+[,\.]\d{2})\s*€?\s+(\d+[,\.]\d{2})\s*€?", clean_ehp)
        if grade_match:
            stabstahl_val = round(float(grade_match.group(2).replace(",", ".")), 2)
            rows.append({"Date": ehp_date, "Steel14057": stabstahl_val})
    except Exception as e:
        print(f"Warning: EHP Edelstahl scrape returned: {e}")

    if not rows:
        return pd.DataFrame(columns=list(("Date", "Steel14057")))
    return pd.DataFrame(rows).drop_duplicates(subset=list(("Date",)), keep="first")

def scrape_chinatungsten_article():
    """Scrape 65% Wolframite Concentrate price from the specified ChinaTungsten article (no fabrication)."""
    rows = list()
    try:
        print(f"Scraping ChinaTungsten article: {CHINATUNGSTEN_URL}")
        resp = requests.get(CHINATUNGSTEN_URL, headers=HEADERS, timeout=25)
        resp.encoding = "utf-8"
        text = resp.text
        date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        price_match = re.search(r"65%黑钨精矿价格报\s*(\d+(?:\.\d+)?)\s*万元", text)
        if date_match and price_match:
            y_str = date_match.group(1)
            m_str = str(int(date_match.group(2))).zfill(2)
            rmb_per_ton = round(float(price_match.group(1)) * 10000)
            rows.append({"Date": f"{y_str}-{m_str}", "Tungsten65": rmb_per_ton})
    except Exception as e:
        print(f"Warning: ChinaTungsten article unreachable from runner: {e}")
    if not rows:
        return pd.DataFrame(columns=list(("Date", "Tungsten65")))
    return pd.DataFrame(rows).drop_duplicates(subset=list(("Date",)))

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
    filtered.drop(columns=list(("Year", "Month")), inplace=True)
    return filtered

def build_combined_dataset():
    gold_url, silver_url, platinum_url, lbma_status = scrape_lbma_portal_endpoints()
    content, active_doc_id, base_url = download_pinksheet_excel()

    df = pd.read_excel(io.BytesIO(content), sheet_name="Monthly Prices", skiprows=4)
    first_col = next(iter(df.columns))
    df.rename(columns={first_col: "RawDate"}, inplace=True)

    df["DateObj"] = pd.to_datetime(df["RawDate"].astype(str), format="%YM%m", errors="coerce")
    df = df.dropna(subset=list(("DateObj",))).copy()
    df["Date"] = df["DateObj"].dt.strftime("%Y-%m")

    selected = {"Date": df["Date"]}
    for wb_col, target_col in COLUMN_MAPPING.items():
        matched = [c for c in df.columns if str(c).strip().startswith(wb_col)]
        if matched:
            first_match = next(iter(matched))
            decimals = 0 if target_col in ("Gold", "Platinum", "Aluminium", "Copper", "Tin") else 2
            selected[target_col] = pd.to_numeric(df[first_match], errors="coerce").round(decimals)

    wb_df = pd.DataFrame(selected)

    lbma_gold = fetch_lbma_monthly_series(gold_url, "Gold_LBMA", decimals=0, extract_fx=True)
    lbma_silver = fetch_lbma_monthly_series(silver_url, "Silver_LBMA", decimals=2)
    lbma_plat = fetch_lbma_monthly_series(platinum_url, "Platinum_LBMA", decimals=0)
    steel_df = scrape_steel_14057_surcharges()
    tungsten_df = scrape_chinatungsten_article()

    merged = pd.merge(wb_df, lbma_gold, on="Date", how="outer")
    merged = pd.merge(merged, lbma_silver, on="Date", how="outer")
    merged = pd.merge(merged, lbma_plat, on="Date", how="outer")
    merged = pd.merge(merged, steel_df, on="Date", how="outer")
    merged = pd.merge(merged, tungsten_df, on="Date", how="outer")

    if "Gold_LBMA" in merged.columns:
        merged["Gold"] = merged["Gold_LBMA"].combine_first(merged.get("Gold"))
        merged.drop(columns=list(("Gold_LBMA",)), inplace=True)
    if "Silver_LBMA" in merged.columns:
        merged["Silver"] = merged["Silver_LBMA"].combine_first(merged.get("Silver"))
        merged.drop(columns=list(("Silver_LBMA",)), inplace=True)
    if "Platinum_LBMA" in merged.columns:
        merged["Platinum"] = merged["Platinum_LBMA"].combine_first(merged.get("Platinum"))
        merged.drop(columns=list(("Platinum_LBMA",)), inplace=True)

    final_df = filter_semi_annual_and_monthly(merged)
    return final_df, active_doc_id, base_url, lbma_status

def main():
    os.makedirs("data", exist_ok=True)
    final_df, active_doc_id, base_url, lbma_status = build_combined_dataset()

    payload = {
        "metadata": {
            "document_id": active_doc_id,
            "lbma_portal": LBMA_PORTAL_URL,
            "lbma_status": lbma_status,
            "steel_14057_sources": list((STEEL_EHP_URL, STEEL_EINSAL_DE_URL)),
            "chinatungsten_source": CHINATUNGSTEN_URL,
            "source_portal": f"{base_url}/",
            "source_monthly_xlsx": f"{base_url}/related/CMO-Historical-Data-Monthly.xlsx",
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
