from __future__ import annotations

import argparse
from pathlib import Path

from .collector import collect_all_once
from .db import WeatherDatabase
from .readings_csv import export_readings_csv, import_readings_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Macau weather data site management tools")
    parser.add_argument(
        "command",
        choices=["init-db", "collect-once", "backup", "import-readings-csv", "export-readings-csv"],
    )
    parser.add_argument("--db", default="data/weather.sqlite", help="SQLite database path")
    parser.add_argument("--csv", default="data/github_pages_readings.csv", help="Weather readings CSV path")
    args = parser.parse_args()

    db = WeatherDatabase(Path(args.db))
    db.init()

    if args.command == "init-db":
        print(f"Database initialized: {db.path}")
    elif args.command == "collect-once":
        result = collect_all_once(db)
        print(f"Collection complete, inserted {result['inserted_count']} readings, external={result['external']}")
    elif args.command == "backup":
        target = db.backup()
        print(f"Backup complete: {target}")
    elif args.command == "import-readings-csv":
        count = import_readings_csv(db, args.csv)
        print(f"Imported {count} readings from {args.csv}")
    elif args.command == "export-readings-csv":
        count = export_readings_csv(db, args.csv)
        print(f"Exported {count} readings to {args.csv}")


if __name__ == "__main__":
    main()
