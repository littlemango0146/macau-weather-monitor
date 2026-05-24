from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any

from .external_sources import (
    AIR_QUALITY_CACHE_KEY,
    FORECAST_CACHE_KEY,
    WARNINGS_CACHE_KEY,
    refresh_air_quality,
    refresh_official_forecast,
    refresh_official_warnings,
)
from .stations import STATIONS_BY_CODE

BRIDGE_CODES = {"MN", "MS", "PN", "PS", "PG", "PV", "PL"}


def beaufort(speed_kmh: float | None) -> dict[str, Any]:
    speed = float(speed_kmh or 0)
    scale = [
        (1, 0, "無風"),
        (5, 1, "軟風"),
        (11, 2, "輕風"),
        (19, 3, "微風"),
        (28, 4, "和風"),
        (38, 5, "清勁風"),
        (49, 6, "強風"),
        (61, 7, "疾勁風"),
        (74, 8, "烈風"),
        (88, 9, "強烈風"),
        (102, 10, "暴風"),
        (117, 11, "狂風"),
        (10_000, 12, "颶風"),
    ]
    for upper, level, label in scale:
        if speed <= upper:
            return {"level": level, "label": label}
    return {"level": 12, "label": "颶風"}


def heat_index(temp_c: float | None, humidity: float | None) -> float | None:
    if temp_c is None or humidity is None:
        return None
    t = float(temp_c)
    h = float(humidity)
    if t < 27:
        return round(t, 1)
    tf = t * 9 / 5 + 32
    hi = (
        -42.379
        + 2.04901523 * tf
        + 10.14333127 * h
        - 0.22475541 * tf * h
        - 0.00683783 * tf * tf
        - 0.05481717 * h * h
        + 0.00122874 * tf * tf * h
        + 0.00085282 * tf * h * h
        - 0.00000199 * tf * tf * h * h
    )
    return round((hi - 32) * 5 / 9, 1)


def comfort_label(hi: float | None) -> str:
    if hi is None:
        return "資料不足"
    if hi < 27:
        return "舒適"
    if hi < 32:
        return "偏熱"
    if hi < 38:
        return "炎熱"
    if hi < 44:
        return "酷熱"
    return "危險酷熱"


def _latest_items(latest: dict[str, dict]) -> list[dict]:
    return [row for row in latest.values() if row]


def wind_index(latest: dict[str, dict]) -> dict[str, Any]:
    items = _latest_items(latest)
    bridge = [row for row in items if row["station_code"] in BRIDGE_CODES]
    land = [row for row in items if row["station_code"] not in BRIDGE_CODES]
    strongest = max(items, key=lambda row: row.get("wind_gust") or row.get("wind_speed") or 0, default=None)
    mean_bridge = mean([row["wind_speed"] for row in bridge if row.get("wind_speed") is not None]) if bridge else None
    mean_land = mean([row["wind_speed"] for row in land if row.get("wind_speed") is not None]) if land else None
    max_wind = max([row.get("wind_speed") or 0 for row in items], default=0)
    max_gust = max([row.get("wind_gust") or 0 for row in items], default=0)

    return {
        "updated_at": _latest_time(items),
        "bridge_average_kmh": round(mean_bridge, 1) if mean_bridge is not None else None,
        "land_average_kmh": round(mean_land, 1) if mean_land is not None else None,
        "max_average_kmh": round(max_wind, 1),
        "max_gust_kmh": round(max_gust, 1),
        "beaufort": beaufort(max_wind),
        "strongest_station": strongest,
        "bridge_stations": bridge,
        "land_stations": land,
    }


def comfort_index(latest: dict[str, dict]) -> dict[str, Any]:
    items = _latest_items(latest)
    enriched = []
    for row in items:
        hi = heat_index(row.get("temperature"), row.get("humidity"))
        enriched.append({**row, "heat_index": hi, "comfort": comfort_label(hi)})
    hottest = max(enriched, key=lambda row: row.get("heat_index") or -100, default=None)
    coolest = min(enriched, key=lambda row: row.get("temperature") or 100, default=None)
    humid = max(enriched, key=lambda row: row.get("humidity") or -1, default=None)
    return {
        "updated_at": _latest_time(items),
        "hottest": hottest,
        "coolest": coolest,
        "most_humid": humid,
        "stations": enriched,
    }


def warning_summary(latest: dict[str, dict], db=None, fetch_live: bool = False) -> dict[str, Any]:
    items = _latest_items(latest)
    max_gust = max([row.get("wind_gust") or 0 for row in items], default=0)
    max_rain = max([row.get("rainfall_hour") or 0 for row in items], default=0)
    max_heat = max([heat_index(row.get("temperature"), row.get("humidity")) or 0 for row in items], default=0)
    warnings = []
    official_status = "pending_source"
    if fetch_live and db is not None:
        refresh_official_warnings(db)
    if db is not None:
        cached = db.get_external_cache(WARNINGS_CACHE_KEY)
        if cached:
            warnings.extend(cached.get("items", []))
            official_status = cached.get("status", "active")
    if max_gust >= 63:
        warnings.append({"type": "強風提示", "level": "watch", "message": f"最高陣風 {max_gust:.1f} km/h"})
    if max_rain >= 20:
        warnings.append({"type": "強降雨提示", "level": "watch", "message": f"最高一小時雨量 {max_rain:.1f} mm"})
    if max_heat >= 35:
        warnings.append({"type": "酷熱提示", "level": "watch", "message": f"最高體感溫度 {max_heat:.1f} °C"})
    official_items = [item for item in warnings if item.get("source")]
    return {
        "updated_at": _latest_time(items),
        "source": "SMG 官方警告 XML + 本地觀測派生提示",
        "official_status": "active" if official_items else official_status,
        "items": warnings,
    }


def water_level_summary() -> dict[str, Any]:
    return {
        "status": "pending_source",
        "source": "等待接入 SMG/海事水位資料",
        "items": [],
        "sections": ["全澳水位", "澳門區水位", "離島區水位", "24 小時水位圖"],
    }


def air_quality_summary(db=None, fetch_live: bool = False) -> dict[str, Any]:
    if fetch_live and db is not None:
        refresh_air_quality(db)
    if db is not None:
        cached = db.get_external_cache(AIR_QUALITY_CACHE_KEY)
        if cached:
            return cached
    return {
        "status": "pending_source",
        "source": "等待接入 SMG 空氣質量 XML",
        "items": [],
        "metrics": ["AQI", "PM2.5", "PM10", "NO2", "O3", "SO2", "CO"],
    }


def database_summary(db) -> dict[str, Any]:
    latest = db.latest_by_station()
    metrics = [
        "temperature",
        "humidity",
        "dew_point",
        "wind_speed",
        "wind_gust",
        "rainfall_hour",
        "rainfall_day",
        "mean_sea_level_pressure",
    ]
    return {
        "station_count": len(latest),
        "latest_data_time": db.latest_data_time(),
        "latest_fetch": db.latest_fetch(),
        "metrics": metrics,
        "datasets": [
            {"name": "氣象站觀測", "status": "active"},
            {"name": "風力指數", "status": "derived"},
            {"name": "三天天氣預測", "status": "active"},
            {"name": "水位監測", "status": "pending_source"},
            {"name": "空氣質量", "status": "pending_source"},
            {"name": "天氣警告", "status": "pending_source"},
        ],
    }


def official_forecast_summary(db=None, fetch_live: bool = False) -> dict[str, Any]:
    if fetch_live and db is not None:
        refresh_official_forecast(db)
    if db is not None:
        cached = db.get_external_cache(FORECAST_CACHE_KEY)
        if cached:
            return cached
    return {
        "status": "pending_source",
        "source": "等待接入 SMG 七天天氣預報 XML",
        "items": [],
        "note": "官方七日預報會與本地三天 ML 預測分開顯示。",
    }


def _latest_time(items: list[dict]) -> str | None:
    times = [row.get("record_time") for row in items if row.get("record_time")]
    if not times:
        return None
    try:
        return max(datetime.fromisoformat(t) for t in times).isoformat()
    except ValueError:
        return max(times)
