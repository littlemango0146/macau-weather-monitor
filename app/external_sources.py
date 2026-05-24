from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .db import WeatherDatabase
from .smg import (
    SMG_AIR_QUALITY_URL,
    SMG_SEVEN_DAY_FORECAST_URL,
    SMG_WARNING_URLS,
    fetch_xml,
    parse_air_quality_forecast,
    parse_seven_day_forecast,
    parse_warning_xml,
)

FORECAST_CACHE_KEY = "official_forecast"
AIR_QUALITY_CACHE_KEY = "air_quality"
WARNINGS_CACHE_KEY = "official_warnings"


def refresh_external_sources(db: WeatherDatabase) -> dict[str, str]:
    results = {
        FORECAST_CACHE_KEY: refresh_official_forecast(db),
        AIR_QUALITY_CACHE_KEY: refresh_air_quality(db),
        WARNINGS_CACHE_KEY: refresh_official_warnings(db),
    }
    return results


def refresh_official_forecast(db: WeatherDatabase) -> str:
    try:
        payload = parse_seven_day_forecast(fetch_xml(SMG_SEVEN_DAY_FORECAST_URL, timeout=8))
        db.upsert_external_cache(
            FORECAST_CACHE_KEY,
            SMG_SEVEN_DAY_FORECAST_URL,
            payload.get("status", "active"),
            payload,
        )
        return "ok"
    except Exception as exc:
        _store_error(db, FORECAST_CACHE_KEY, SMG_SEVEN_DAY_FORECAST_URL, exc)
        return "error"


def refresh_air_quality(db: WeatherDatabase) -> str:
    try:
        payload = parse_air_quality_forecast(fetch_xml(SMG_AIR_QUALITY_URL, timeout=8))
        db.upsert_external_cache(
            AIR_QUALITY_CACHE_KEY,
            SMG_AIR_QUALITY_URL,
            payload.get("status", "active"),
            payload,
        )
        return "ok"
    except Exception as exc:
        _store_error(db, AIR_QUALITY_CACHE_KEY, SMG_AIR_QUALITY_URL, exc)
        return "error"


def refresh_official_warnings(db: WeatherDatabase) -> str:
    items = _fetch_official_warnings()
    payload = {
        "status": "active",
        "source": "SMG official warning XML",
        "items": items,
    }
    db.insert_warning_events(items)
    status = "active" if any(item.get("status") != "unavailable" for item in payload["items"]) else "unavailable"
    payload["status"] = status
    db.upsert_external_cache(WARNINGS_CACHE_KEY, payload["source"], status, payload)
    return "ok" if status == "active" else "error"


def _fetch_official_warnings() -> list[dict[str, Any]]:
    def fetch_one(warning_type: str, url: str) -> dict[str, Any]:
        try:
            item = parse_warning_xml(fetch_xml(url, timeout=6), warning_type, url)
            item["level"] = "official" if item["status"] == "active" else "inactive"
            return item
        except Exception as exc:
            return {
                "type": warning_type,
                "status": "unavailable",
                "level": "inactive",
                "message": f"官方資料暫時無法讀取：{exc}",
                "source": url,
            }

    official = []
    with ThreadPoolExecutor(max_workers=min(5, len(SMG_WARNING_URLS))) as executor:
        futures = [
            executor.submit(fetch_one, warning_type, url)
            for warning_type, url in SMG_WARNING_URLS.items()
        ]
        for future in as_completed(futures):
            official.append(future.result())
    return official


def _store_error(db: WeatherDatabase, cache_key: str, source: str, exc: Exception) -> None:
    cached = db.get_external_cache(cache_key)
    if cached:
        cached["status"] = "stale"
        cached["error"] = str(exc)
        db.upsert_external_cache(cache_key, source, "stale", cached, str(exc))
        return
    db.upsert_external_cache(
        cache_key,
        source,
        "unavailable",
        {"status": "unavailable", "source": source, "items": [], "error": str(exc)},
        str(exc),
    )
