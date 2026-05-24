from __future__ import annotations

from .db import WeatherDatabase
from .external_sources import refresh_external_sources
from .smg import fetch_actual_weather, parse_actual_weather


def collect_once(db: WeatherDatabase) -> int:
    try:
        xml_bytes = fetch_actual_weather()
        readings = parse_actual_weather(xml_bytes)
        inserted = db.insert_readings(readings)
        db.log_fetch("ok", inserted, f"parsed {len(readings)} stations")
        return inserted
    except Exception as exc:
        db.log_fetch("error", 0, str(exc))
        raise


def collect_all_once(db: WeatherDatabase, raise_on_weather_error: bool = True) -> dict:
    inserted = 0
    weather_status = "ok"
    weather_error = None
    try:
        inserted = collect_once(db)
    except Exception as exc:
        weather_status = "error"
        weather_error = exc
    external = refresh_external_sources(db)
    if weather_error is not None and raise_on_weather_error:
        raise weather_error
    return {"inserted_count": inserted, "weather_status": weather_status, "external": external}
