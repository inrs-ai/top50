import requests
import pandas as pd
import json
from bs4 import BeautifulSoup

URL = "https://stockanalysis.com/stocks/"

def fetch_top_50():
    """抓取美股市值前 50 名公司"""
    resp = requests.get(URL, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")

    rows = []
    for tr in table.find("tbody").find_all("tr")[:50]:
        cols = tr.find_all("td")
        symbol = cols[0].text.strip()
        name = cols[1].text.strip()
        industry = cols[3].text.strip() if len(cols) > 3 else "Unknown"

        rows.append({
            "symbol": symbol,
            "name": name,
            "industry": industry
        })

    return rows

def save_json(data):
    with open("tickers.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    print("Fetching top 50 US companies by market cap...")
    data = fetch_top_50()
    save_json(data)
    print("tickers.json updated successfully.")

if __name__ == "__main__":
    main()
