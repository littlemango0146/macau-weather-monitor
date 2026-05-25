from __future__ import annotations

import json
from pathlib import Path

from .db import WeatherDatabase
from .dashboard import (
    air_quality_summary,
    comfort_index,
    database_summary,
    official_forecast_summary,
    warning_summary,
    water_level_summary,
    wind_index,
)
from .stations import station_list

ALL_METRICS = [
    "temperature",
    "humidity",
    "dew_point",
    "wind_speed",
    "wind_gust",
    "rainfall_current",
    "rainfall_hour",
    "rainfall_day",
    "mean_sea_level_pressure",
    "station_pressure",
]


def build_offline_html(db_path: str | Path = "data/weather.sqlite", output: str | Path = "dist/offline.html") -> Path:
    db = WeatherDatabase(db_path)
    db.init()
    latest = db.latest_by_station()
    stations = [{**station, "latest": latest.get(station["code"])} for station in station_list()]

    history: dict[str, list[dict]] = {}
    for station in stations:
        code = station["code"]
        rows: list[dict] = []
        for metric in ALL_METRICS:
            try:
                metric_rows = db.history(code, metric)
            except ValueError:
                continue
            for row in metric_rows:
                existing = next((item for item in rows if item["record_time"] == row["record_time"]), None)
                if existing is None:
                    existing = {"record_time": row["record_time"]}
                    rows.append(existing)
                existing[metric] = row["value"]
        history[code] = sorted(rows, key=lambda item: item["record_time"])

    payload = {
        "stations": stations,
        "history": history,
        "health": {
            "database": "offline",
            "latest_fetch": db.latest_fetch(),
            "latest_success": db.latest_success(),
            "latest_data_time": db.latest_data_time(),
        },
        "daily_summary": db.daily_summary(),
        "data_quality": {
            "latest_data_time": db.latest_data_time(),
            "reading_count": db.count_readings(),
            "station_count": len(latest),
            "expected_station_count": len(station_list()),
            "external_sources": db.list_external_cache(),
            "latest_fetch": db.latest_fetch(),
            "latest_success": db.latest_success(),
        },
        "warning_events": {"items": db.list_warning_events()},
        "dashboard": {
            "wind_index": wind_index(latest),
            "comfort_index": comfort_index(latest),
            "warnings": warning_summary(latest),
            "water_level": water_level_summary(),
            "air_quality": air_quality_summary(),
            "database": database_summary(db),
            "official_forecast": official_forecast_summary(),
        },
    }

    static_dir = Path(__file__).parent / "static"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    leaflet_css = (static_dir / "vendor" / "leaflet" / "leaflet.css").read_text(encoding="utf-8")
    leaflet_js = (static_dir / "vendor" / "leaflet" / "leaflet.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")
    chart_lite = (static_dir / "chart-lite.js").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")

    html = html.replace(
        '<link rel="stylesheet" href="/static/vendor/leaflet/leaflet.css?v=20260524-overview1">',
        f"<style>\n{leaflet_css}\n</style>",
    )
    html = html.replace(
        '<link rel="stylesheet" href="/static/styles.css?v=20260524-overview1">',
        f"<style>\n{styles}\n</style>",
    )
    html = html.replace(
        '<script src="/static/vendor/leaflet/leaflet.js?v=20260524-overview1"></script>',
        f"<script>\n{leaflet_js}\n</script>",
    )
    html = html.replace(
        '<script src="/static/chart-lite.js?v=20260524-overview1"></script>',
        f"<script>\n{chart_lite}\n</script>",
    )
    html = html.replace(
        '<script src="/static/app.js?v=20260524-overview1"></script>',
        f"<script>window.OFFLINE_DATA = {json.dumps(payload, ensure_ascii=False)};</script>\n"
        f"<script>\n{script}\n</script>",
    )

    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


if __name__ == "__main__":
    print(build_offline_html())
