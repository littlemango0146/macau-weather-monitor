from __future__ import annotations

import argparse
from pathlib import Path

from .collector import collect_all_once
from .db import WeatherDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="澳門氣象資料站管理工具")
    parser.add_argument("command", choices=["init-db", "collect-once", "backup"])
    parser.add_argument("--db", default="data/weather.sqlite", help="SQLite database path")
    args = parser.parse_args()

    db = WeatherDatabase(Path(args.db))
    db.init()

    if args.command == "init-db":
        print(f"資料庫已初始化：{db.path}")
    elif args.command == "collect-once":
        result = collect_all_once(db)
        print(f"抓取完成，新增 {result['inserted_count']} 筆資料，官方資料：{result['external']}")
    elif args.command == "backup":
        target = db.backup()
        print(f"備份完成：{target}")


if __name__ == "__main__":
    main()
