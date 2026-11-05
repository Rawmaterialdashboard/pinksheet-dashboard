name: Scrape World Bank Pink Sheet

on:
  schedule:
    - cron: '0 2 6 * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  scrape-and-update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install pandas openpyxl requests

      - name: Run Pink Sheet scraper
        run: python scripts/fetch_pinksheet.py

      - name: Commit and push updated JSON
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add data/dashboard_data.json
          git commit -m "chore: update World Bank Pink Sheet data" || exit 0
          git push
