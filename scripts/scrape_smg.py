"""
SMG 澳門氣象局歷史天氣爬蟲
爬取 frame.smg.gov.mo/query/weather/query_obs.php
支援範圍：2005-01 ~ 今天

用法：
    python scripts/scrape_smg.py               # 爬取所有缺漏月份
    python scripts/scrape_smg.py --full        # 從 2005-01 全量爬取
    python scripts/scrape_smg.py --from 2026-01  # 從指定年月爬起
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

CSV_PATH = Path(__file__).parent.parent / "data" / "smg_history.csv"
QUERY_URL = "https://frame.smg.gov.mo/query/weather/query_obs.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://frame.smg.gov.mo/query/weather/c_panel.php",
    "Content-Type": "application/x-www-form-urlencoded",
}

COLUMNS = [
    "date", "pressure_hpa",
    "temp_max", "temp_avg", "temp_min",
    "dew_point", "humidity_pct", "sunshine_h",
    "wind_direction", "wind_speed_kmh", "rainfall_mm",
]


def fetch_month(year: int, month: int, retries: int = 3) -> list[dict]:
    """抓取某個月的每日觀測資料，回傳 list of dict"""
    month_str = f"{year}-{month:02d}"
    body = urlencode({"dateType": "month", "month": month_str, "lang": "c"}).encode()

    for attempt in range(retries):
        try:
            req = Request(QUERY_URL, data=body, headers=HEADERS, method="POST")
            with urlopen(req, timeout=20) as resp:
                raw = resp.read()
            break
        except (URLError, TimeoutError) as e:
            if attempt == retries - 1:
                print(f"  fetch failed: {e}")
                return []
            time.sleep(2 ** attempt)

    soup = BeautifulSoup(raw, "html.parser")
    rows = []

    for tr in soup.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 11:
            continue
        # 第一欄應是日期 yyyy-mm-dd
        if not re.match(r"\d{4}-\d{2}-\d{2}", tds[0]):
            continue

        def safe_float(val: str) -> float:
            if not val:
                return 0.0
            # VST / Trace = 微量降雨，視為 0
            if val.upper() in ("VST", "TRACE", "T", "TR", "-"):
                return 0.0
            try:
                return float(val)
            except ValueError:
                return 0.0

        rows.append({
            "date":           tds[0],
            "pressure_hpa":   safe_float(tds[1]),
            "temp_max":       safe_float(tds[2]),
            "temp_avg":       safe_float(tds[3]),
            "temp_min":       safe_float(tds[4]),
            "dew_point":      safe_float(tds[5]),
            "humidity_pct":   safe_float(tds[6]),
            "sunshine_h":     safe_float(tds[7]),
            "wind_direction": tds[8],
            "wind_speed_kmh": safe_float(tds[9]),
            "rainfall_mm":    safe_float(tds[10]),
        })

    return rows


def months_to_fetch(from_date: date, to_date: date) -> list[tuple[int, int]]:
    """生成 (year, month) 列表"""
    result = []
    cur = date(from_date.year, from_date.month, 1)
    end = date(to_date.year, to_date.month, 1)
    while cur <= end:
        result.append((cur.year, cur.month))
        # 下一個月
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full",  action="store_true", help="從 2005-01 全量爬取")
    parser.add_argument("--from",  dest="from_date", default=None, help="起始年月 yyyy-mm")
    parser.add_argument("--delay", type=float, default=0.8, help="每次請求間隔秒數（預設 0.8）")
    args = parser.parse_args()

    today = date.today()

    # 決定起始日期
    if args.full:
        start = date(2005, 1, 1)
    elif args.from_date:
        y, m = map(int, args.from_date.split("-"))
        start = date(y, m, 1)
    else:
        # 預設：從 CSV 最後一筆的下個月開始（增量更新）
        if CSV_PATH.exists():
            existing = pd.read_csv(CSV_PATH)
            last_date = pd.to_datetime(existing["date"]).max().date()
            # Re-fetch current month to ensure completeness
            start = date(last_date.year, last_date.month, 1)
            print(f"Incremental update from {start}")
        else:
            start = date(2005, 1, 1)
            print("No existing CSV, full fetch from 2005-01")

    months = months_to_fetch(start, today)
    print(f"Fetching {len(months)} months ({start} ~ {today})")

    all_rows: list[dict] = []
    for i, (y, m) in enumerate(months, 1):
        label = f"{y}-{m:02d}"
        rows = fetch_month(y, m)
        if rows:
            all_rows.extend(rows)
            print(f"  [{i:3d}/{len(months)}] {label}  {len(rows):2d} days")
        else:
            print(f"  [{i:3d}/{len(months)}] {label}  no data")
        if i < len(months):
            time.sleep(args.delay)

    if not all_rows:
        print("No data fetched, exiting")
        return

    df_new = pd.DataFrame(all_rows, columns=COLUMNS)
    df_new["date"] = pd.to_datetime(df_new["date"])

    # 合併舊資料
    if CSV_PATH.exists() and not args.full:
        df_old = pd.read_csv(CSV_PATH)
        df_old["date"] = pd.to_datetime(df_old["date"])
        # 把舊資料中已被新資料覆蓋的日期刪掉
        new_dates = set(df_new["date"])
        df_old = df_old[~df_old["date"].isin(new_dates)]
        df_combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_combined = df_new

    df_combined = df_combined.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    df_combined["date"] = df_combined["date"].dt.strftime("%Y-%m-%d")

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_combined.to_csv(CSV_PATH, index=False)

    print(f"\nSaved: {CSV_PATH}")
    print(f"  Total: {len(df_combined)}  ({df_combined['date'].iloc[0]} ~ {df_combined['date'].iloc[-1]})")
    print(f"  New/Updated: {len(df_new)} days")


if __name__ == "__main__":
    main()
