#!/usr/bin/env python3
"""
scraper.py
Fetches the DGFT currency list page, parses the table for currency Import/Export rates (vs INR),
and writes a structured JSON file at static/customs-rates.json.

Requirements:
  pip install requests beautifulsoup4
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DGFT_URL = "https://www.dgft.gov.in/CP/?opt=currency-list-exchange-rates"
OUT_PATH = Path("static") / "customs-rates.json"
HEADERS = {
    "User-Agent": "CustomsRatesBot/1.0 (+https://github.com/itsunique00/indian-customs-exchange-rate)"
}
TIMEOUT = 15.0


def requests_session_with_retries(retries=3, backoff=1.0, status_forcelist=(500,502,503,504)):
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=backoff, status_forcelist=status_forcelist, allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def parse_rates_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    # The page contains a table of currencies. We attempt to find the first table with relevant headers.
    tables = soup.find_all("table")
    if not tables:
        raise ValueError("No tables found on the page.")
    # Heuristic: find table with header cells mentioning 'Currency' and 'Import' / 'Export'
    target = None
    for tbl in tables:
        header_text = " ".join([th.get_text(strip=True).lower() for th in tbl.find_all("th")])
        if "import" in header_text and "export" in header_text and "currency" in header_text:
            target = tbl
            break
    if target is None:
        # fallback: use first table
        target = tables[0]

    rates = {}
    for row in target.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
        # Common expected layout: Currency | Import Rate | Export Rate | ... (or similar)
        if len(cells) < 3:
            continue
        # Try to heuristically find where import/export are
        # Convert numeric-like strings by stripping commas
        # Find currency name (first non-empty text cell that is not a header 'Currency')
        currency = cells[0]
        # attempt to find import/export within the row
        import_rate = None
        export_rate = None
        # simple heuristics: last two numeric cells are rates
        numeric_cells = [c for c in cells if any(ch.isdigit() for ch in c)]
        if len(numeric_cells) >= 2:
            # pick last two numeric candidates
            export_rate_str = numeric_cells[-1]
            import_rate_str = numeric_cells[-2]
            def to_float(s):
                try:
                    return float(s.replace(",", "").replace("−", "-"))
                except:
                    return None
            import_rate = to_float(import_rate_str)
            export_rate = to_float(export_rate_str)
        # store only if we have at least one numeric value
        if import_rate is None and export_rate is None:
            continue
        rates[currency] = {
            "import_rate_inr": import_rate,
            "export_rate_inr": export_rate,
            "raw_row": cells
        }
    if not rates:
        raise ValueError("No currency rows were parsed. The page structure may have changed.")
    return rates


def main():
    s = requests_session_with_retries()
    try:
        resp = s.get(DGFT_URL, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"Network error while fetching {DGFT_URL}: {e}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code != 200:
        print(f"Received HTTP {resp.status_code} from {DGFT_URL}. The site may be down or blocked.", file=sys.stderr)
        sys.exit(3)

    html = resp.text
    try:
        rates = parse_rates_from_html(html)
    except Exception as e:
        print(f"Failed to parse rates from DGFT page: {e}", file=sys.stderr)
        sys.exit(4)

    out = {
        "meta": {
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
            "fetched_from": DGFT_URL,
            "base_currency": "INR",
            "notes": "Parsed from DGFT currency table. Verify results manually if values look unexpected."
        },
        "rates": rates
    }

    try:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"Wrote rates to {OUT_PATH} (currencies: {len(rates)})")
    except Exception as e:
        print(f"Failed to write output file: {e}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
