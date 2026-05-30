from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import WeatherDatabase
from .models import WeatherReading

READING_CSV_FIELDS = [
    "station_code",
    "station_name",
    "record_time",
    "temperature",
    "humidity",
    "dew_point",
    "wind_gust",
    "wind_speed",
    "rainfall_current",
    "rainfall_hour",
    "rainfall_day",
    "wind_direction",
    "wind_degree",
    "wind_description",
    "mean_sea_level_pressure",
    "station_pressure",
]

FLOAT_FIELDS = {
    "temperature",
    "humidity",
    "dew_point",
    "wind_gust",
    "wind_speed",
    "rainfall_current",
    "rainfall_hour",
    "rainfall_day",
    "wind_degree",
    "mean_sea_level_pressure",
    "station_pressure",
}


def import_readings_csv(db: WeatherDatabase, csv_path: str | Path) -> int:
    path = Path(csv_path)
    if not path.exists():
        return 0

    readings: list[WeatherReading] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("station_code") or not row.get("record_time"):
                continue
            readings.append(_reading_from_csv_row(row))

    return db.insert_readings(readings)


def export_readings_csv(db: WeatherDatabase, csv_path: str | Path) -> int:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = db.export_readings(limit=10_000_000)
    rows.sort(key=lambda row: (row["record_time"], row["station_code"]))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=READING_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in READING_CSV_FIELDS})

    return len(rows)


def _reading_from_csv_row(row: dict[str, Any]) -> WeatherReading:
    values = {field: _empty_to_none(row.get(field)) for field in READING_CSV_FIELDS}
    for field in FLOAT_FIELDS:
        values[field] = _to_float(values.get(field))
    return WeatherReading(
        station_code=str(values["station_code"]),
        station_name=str(values.get("station_name") or values["station_code"]),
        record_time=datetime.fromisoformat(str(values["record_time"]).replace(" ", "T")),
        temperature=values["temperature"],
        humidity=values["humidity"],
        dew_point=values["dew_point"],
        wind_gust=values["wind_gust"],
        wind_speed=values["wind_speed"],
        rainfall_current=values["rainfall_current"],
        rainfall_hour=values["rainfall_hour"],
        rainfall_day=values["rainfall_day"],
        wind_direction=values["wind_direction"],
        wind_degree=values["wind_degree"],
        wind_description=values["wind_description"],
        mean_sea_level_pressure=values["mean_sea_level_pressure"],
        station_pressure=values["station_pressure"],
    )


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    value = str(value).strip()
    return value if value != "" else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value
