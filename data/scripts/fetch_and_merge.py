import os
import io
import pandas as pd
import requests

# 1. 基础配置
PINK_SHEET_URL = "https://pubdocs.worldbank.org/en/294191429302848505/CMO-Historical-Data-Monthly.xlsx"
MANUAL_CSV_PATH = "data/manual_metrics.csv"
OUTPUT_JSON_PATH = "data/dashboard_data.json"

# 指标映射字典（世行列名 -> 统一标准字段名）
COMS_MAP = {
    'GOLD': 'Gold',
    'ALUMINUM': 'Aluminium',
    'COPPER': 'Copper',
    'TIN': 'Tin',
    'SILVER': 'Silver',
    'RUBBER': 'Rubber'
}

def fetch_world_bank_data():
    """从世界银行官网下载 Pink Sheet 并解析月度价格表"""
    print(">>> 正在从世界银行获取 Pink Sheet 数据...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    response = requests.get(PINK_SHEET_URL, headers=headers, timeout=60)
    response.raise_for_status()

    # 跳过前 4 行元数据说明，读取 "Monthly Prices" 工作表
    df = pd.read_excel(io.BytesIO(response.content), sheet_name="Monthly Prices", skiprows=4)
    
    # 提取首列作为日期
    df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'], format='%YM%m', errors='coerce')
    df.dropna(subset=['Date'], inplace=True)

    # 规范化列名
    available_cols = {'Date': 'Date'}
    for raw_col in df.columns:
        for key, target_name in COMS_MAP.items():
            if str(raw_col).strip().upper() == key or str(raw_col).strip().upper().startswith(key):
                available_cols[raw_col] = target_name

    df = df[list(available_cols.keys())].rename(columns=available_cols)
    return df

def process_time_rules(df):
    """
    处理时间抽样规则：
    - 2016 至 2023 年：半年度更新（仅提取 6月 与 12月）
    - 2024 年至今：月度高频更新（提取每月数据）
    """
    print(">>> 正在进行半年度/月度重采样清洗...")
    df['Year'] = df['Date'].dt.year
    df['Month'] = df['Date'].dt.month

    # 过滤掉 2016 年以前的历史数据
    df = df[df['Year'] >= 2016].copy()

    # 拆分两个时间周期
    df_semi_annual = df[(df['Year'] >= 2016) & (df['Year'] < 2024)]
    df_monthly = df[df['Year'] >= 2024]

    # 半年度采样（6月和12月）
    df_semi_filtered = df_semi_annual[df_semi_annual['Month'].isin([6, 12])]

    # 拼接并保持时序
    df_merged = pd.concat([df_semi_filtered, df_monthly], ignore_index=True)
    df_merged.sort_values('Date', inplace=True)

    # 格式化日期为 YYYY-MM
    df_merged['Date_Str'] = df_merged['Date'].dt.strftime('%Y-%m')
    df_merged.drop(columns=['Date', 'Year', 'Month'], inplace=True)
    df_merged.rename(columns={'Date_Str': 'Date'}, inplace=True)

    return df_merged

def merge_manual_data(df_auto):
    """合并人工维护的钨、钢数据"""
    if os.path.exists(MANUAL_CSV_PATH):
        print(">>> 检测到手动指标文件，执行数据拼接...")
        df_manual = pd.read_csv(MANUAL_CSV_PATH)
        df_manual['Date'] = df_manual['Date'].astype(str).str.strip()
        df_final = pd.merge(df_auto, df_manual, on='Date', how='left')
    else:
        print(">>> 未发现 manual_metrics.csv，填充默认空值...")
        df_final = df_auto.copy()
        df_final['Tungsten'] = None
        df_final['Steel_Custom'] = None

    return df_final

if __name__ == "__main__":
    try:
        os.makedirs('data', exist_ok=True)
        raw = fetch_world_bank_data()
        cleaned = process_time_rules(raw)
        final_df = merge_manual_data(cleaned)
        
        # 写入 JSON
        final_df.to_json(OUTPUT_JSON_PATH, orient='records', indent=2)
        print(f"✅ 处理成功！已生成统一数据文件: {OUTPUT_JSON_PATH}")
    except Exception as e:
        print(f"❌ 运行异常: {e}")
        raise e


三、 步骤二：配置 GitHub Actions 定时自动更新

创建文件 .github/workflows/update_data.yml，设定每月自动执行、下载数据并自动提交：

name: Auto Update Pink Sheet Data

on:
  schedule:
    # 国际标准时间（UTC）每月 6 号 02:00（对应北京时间 10:00）运行
    - cron: '0 2 6 * *'
  # 支持在 GitHub Actions 页面手动点击 "Run workflow" 测试
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-and-update:
    runs-on: ubuntu-latest
    steps:
      - name: 检出代码仓库
        uses: actions/checkout@v4

      - name: 配置 Python 环境
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: 安装依赖
        run: |
          pip install pandas openpyxl requests

      - name: 运行数据采集与合并脚本
        run: python scripts/fetch_and_merge.py

      - name: 提交并推送更新数据
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add data/dashboard_data.json
          git commit -m "chore: auto-update pink sheet and merged data" || exit 0
          git push
