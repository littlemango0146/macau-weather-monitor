"""
SMG 澳門氣象局歷史每日天氣數據爬蟲（Playwright 版）
來源: https://frame.smg.gov.mo/query/weather/c_panel.php
策略: 每次查詢一個月，瀏覽器等待 iframe 內結果表格載入後提取
輸出: data/smg_history.csv

用法:
    python scripts/scrape_smg_history.py
    python scripts/scrape_smg_history.py --start 2015-01 --end 2026-05
    python scripts/scrape_smg_history.py --test        # 只爬 2024-01 測試
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── 設定 ─────────────────────────────────────────────────────────────────────
PANEL_URL  = "https://frame.smg.gov.mo/query/weather/c_panel.php"
OUTPUT_CSV = Path(__file__).parent.parent / "data" / "smg_history.csv"

DEFAULT_START = (2015, 1)
DEFAULT_END   = (date.today().year, date.today().month)

COLUMNS = [
    "date", "pressure_hpa", "temp_max", "temp_avg", "temp_min",
    "dew_point", "humidity_pct", "sunshine_h",
    "wind_direction", "wind_speed_kmh", "rainfall_mm",
]

DELAY_S   = 2.0   # 每月查詢間隔（秒），避免過度請求
TIMEOUT   = 20000  # 等待表格出現最長 ms


# ── 工具 ─────────────────────────────────────────────────────────────────────
def month_iter(sy, sm, ey, em):
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def parse_rain(val: str) -> str:
    return "0.05" if val.strip().upper() == "VST" else val.strip()


def parse_table_html(html: str, ym: str) -> list[dict]:
    """從 HTML 提取日期格式的數據列"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue
        date_str = tds[0].get_text(strip=True)
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        def g(i):
            return tds[i].get_text(strip=True) if i < len(tds) else ""

        rows.append({
            "date":           date_str,
            "pressure_hpa":   g(1),
            "temp_max":       g(2),
            "temp_avg":       g(3),
            "temp_min":       g(4),
            "dew_point":      g(5),
            "humidity_pct":   g(6),
            "sunshine_h":     g(7),
            "wind_direction": g(8),
            "wind_speed_kmh": g(9),
            "rainfall_mm":    parse_rain(g(10)),
        })
    return rows


# ── 核心爬蟲 ─────────────────────────────────────────────────────────────────
def scrape_month(page, ym: str) -> list[dict]:
    """查詢一個月份，返回數據列表"""

    # 確保月份 radio 選中
    page.locator('input[name="dateType"][value="month"]').check()

    # 填入月份
    page.locator('input[name="month"]').fill(ym)

    # 點擊查詢
    page.get_by_role("button", name="查詢").click()

    # 等待 iframe[name=main] 中的表格出現
    main_frame = page.frame(name="main")
    if main_frame is None:
        # 有時 iframe 尚未建立，稍等
        time.sleep(1.5)
        main_frame = page.frame(name="main")

    if main_frame is None:
        print(f"  [WARN] {ym} 找不到 main frame", file=sys.stderr)
        return []

    try:
        # 等待表格出現（含日期行）
        main_frame.wait_for_selector("table tr td", timeout=TIMEOUT)
    except PWTimeout:
        print(f"  [WARN] {ym} 等待超時", file=sys.stderr)
        return []

    html = main_frame.content()
    rows = parse_table_html(html, ym)
    return rows


def load_existing(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["date"] for row in reader}


def save_rows(rows: list[dict], path: Path, first_write: bool):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if first_write else "a"
    write_header = first_write
    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None, help="起始月份 yyyy-mm")
    parser.add_argument("--end",   default=None, help="結束月份 yyyy-mm")
    parser.add_argument("--test",  action="store_true", help="只爬 2024-01 進行測試")
    args = parser.parse_args()

    if args.test:
        start_y, start_m = 2024, 1
        end_y,   end_m   = 2024, 1
    else:
        if args.start:
            start_y, start_m = map(int, args.start.split("-"))
        else:
            start_y, start_m = DEFAULT_START
        if args.end:
            end_y, end_m = map(int, args.end.split("-"))
        else:
            end_y, end_m = DEFAULT_END

    # 斷點續爬
    existing = load_existing(OUTPUT_CSV)
    if existing:
        last = max(existing)
        last_dt = datetime.strptime(last, "%Y-%m-%d")
        # 從最後一個月重新爬（可能不完整）
        start_y, start_m = last_dt.year, last_dt.month
        print(f"已有 {len(existing)} 筆，最後日期 {last}，從 {start_y}-{start_m:02d} 續爬")

    months = list(month_iter(start_y, start_m, end_y, end_m))
    total  = len(months)
    print(f"共 {total} 個月份（{start_y}-{start_m:02d} → {end_y}-{end_m:02d}）")
    print("=" * 60)

    first_write = not OUTPUT_CSV.exists()
    all_new: list[dict] = []
    saved_count = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(PANEL_URL, wait_until="networkidle", timeout=30000)

        for idx, (y, m) in enumerate(months, 1):
            ym = f"{y:04d}-{m:02d}"
            print(f"[{idx:3d}/{total}] {ym} ...", end=" ", flush=True)

            try:
                rows = scrape_month(page, ym)
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                rows = []

            new_rows = [r for r in rows if r["date"] not in existing]
            existing.update(r["date"] for r in new_rows)
            all_new.extend(new_rows)

            print(f"取得 {len(rows)} 筆，新增 {len(new_rows)} 筆")

            # 每 12 個月寫一次
            if len(all_new) >= 100 or idx == total:
                save_rows(all_new, OUTPUT_CSV, first_write)
                saved_count += len(all_new)
                first_write = False
                all_new = []

            if idx < total:
                time.sleep(DELAY_S)

        browser.close()

    print("=" * 60)
    print(f"完成！共新增 {saved_count} 筆，儲存至：{OUTPUT_CSV}")


if __name__ == "__main__":
    main()
