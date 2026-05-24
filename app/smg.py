from __future__ import annotations

from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .models import WeatherReading

SMG_ACTUAL_WEATHER_URL = "https://xml.smg.gov.mo/c_actualweather.xml"
SMG_SEVEN_DAY_FORECAST_URL = "https://xml.smg.gov.mo/c_7daysforecast.xml"
SMG_AIR_QUALITY_URL = "https://xml.smg.gov.mo/c_foreiqa.xml"
SMG_WARNING_URLS = {
    "熱帶氣旋": "https://xml.smg.gov.mo/c_typhoon.xml",
    "暴雨": "https://xml.smg.gov.mo/c_rainstorm.xml",
    "雷暴": "https://xml.smg.gov.mo/c_thunderstorm.xml",
    "風暴潮": "https://xml.smg.gov.mo/c_stormsurge.xml",
    "季候風": "https://xml.smg.gov.mo/c_monsoon.xml",
}


def fetch_actual_weather(url: str = SMG_ACTUAL_WEATHER_URL, timeout: int = 20) -> bytes:
    return fetch_xml(url, timeout)


def fetch_xml(url: str, timeout: int = 12) -> bytes:
    request = Request(url, headers={"User-Agent": "MacauWeatherStation/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_actual_weather(xml_bytes: bytes) -> list[WeatherReading]:
    root = ET.fromstring(xml_bytes)
    readings: list[WeatherReading] = []

    for station in root.findall(".//WeatherReport/station"):
        code = (station.attrib.get("code") or "").strip().upper()
        name = _text(station, "stationname") or code
        record_time = _parse_time(_text(station, "RecordTime"))
        rainfall = _rainfall_values(station.findall("Rainfall"))
        wind_direction = station.find("WindDirection")

        if not code or record_time is None:
            continue

        readings.append(
            WeatherReading(
                station_code=code,
                station_name=name,
                record_time=record_time,
                temperature=_metric(station, "Temperature"),
                humidity=_metric(station, "Humidity"),
                dew_point=_metric(station, "DewPoint"),
                wind_gust=_metric(station, "WindGust"),
                wind_speed=_metric(station, "WindSpeed"),
                rainfall_current=rainfall.get("3"),
                rainfall_hour=rainfall.get("4"),
                rainfall_day=rainfall.get("5"),
                wind_direction=_metric_text(wind_direction),
                wind_degree=_float(_text(wind_direction, "Degree") if wind_direction is not None else None),
                wind_description=_text(wind_direction, "WindDescription") if wind_direction is not None else None,
                mean_sea_level_pressure=_metric(station, "MeanSeaLevelPressure"),
                station_pressure=_metric(station, "StationPressure"),
            )
        )

    return readings


def parse_seven_day_forecast(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    items = []
    for node in root.findall(".//WeatherForecast"):
        temps = _typed_values(node.findall("Temperature"))
        humidities = _typed_values(node.findall("Humidity"))
        icon = node.find("Icon")
        items.append(
            {
                "valid_for": _text(node, "ValidFor"),
                "day_of_week": _text(node, "c_DayOfWeek"),
                "weather_status": _text(node, "WeatherStatus"),
                "description": _text(node, "WeatherDescription"),
                "icon_url": _text(icon, "IconURL") if icon is not None else None,
                "temp_high": temps.get("1"),
                "temp_low": temps.get("2"),
                "humidity_high": humidities.get("1"),
                "humidity_low": humidities.get("2"),
            }
        )
    return {
        "status": "active" if items else "empty",
        "updated_at": _text(root.find("System"), "SysPubdate"),
        "source": SMG_SEVEN_DAY_FORECAST_URL,
        "items": items,
    }


def parse_air_quality_forecast(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    items = []
    for station in root.findall(".//AQIForecastReport/Station"):
        forecast = station.find("AQIForecast")
        icon = forecast.find("Icon") if forecast is not None else None
        items.append(
            {
                "station_code": (station.attrib.get("code") or "").strip(),
                "station_name": _text(station, "Stationname"),
                "valid_for": _text(forecast, "ValidFor"),
                "value": _text(forecast, "Value"),
                "level": _text(forecast, "AQIForecastDescription"),
                "icon_url": _text(icon, "IconURL") if icon is not None else None,
            }
        )
    complementary = root.find(".//Complementary")
    return {
        "status": "active" if items else "empty",
        "updated_at": _text(root.find("System"), "SysPubdate"),
        "source": SMG_AIR_QUALITY_URL,
        "description": _text(root.find("Custom"), "ReportDescription"),
        "items": items,
        "complementary": {
            "level": _text(complementary, "Level"),
            "sensitive_population_groups": _text(complementary, "SensitivePopulationGroups"),
            "general_public": _text(complementary, "GeneralPublic"),
        },
    }


def parse_warning_xml(xml_bytes: bytes, warning_type: str, source: str | None = None) -> dict:
    root = ET.fromstring(xml_bytes)
    custom = root.find("Custom")
    warning = next(iter(list(custom)), None) if custom is not None and list(custom) else None
    icon = warning.find("Icon") if warning is not None else None
    status = _text(warning, "Status")
    inforce = _text(warning, "Inforce")
    active = status not in (None, "", "0", "NIL") or inforce == "1"
    return {
        "type": warning_type,
        "status": "active" if active else "inactive",
        "updated_at": _text(root.find("System"), "SysPubdate"),
        "issued_at": _text(warning, "IssuedAt"),
        "warn_code": _text(warning, "Warncode"),
        "action": _text(warning, "Action"),
        "message": _text(warning, "Description") or _text(warning, "Major"),
        "icon_url": _text(icon, "IconURL") if icon is not None else None,
        "source": source,
    }


def _rainfall_values(nodes: Iterable[ET.Element]) -> dict[str, float]:
    values: dict[str, float] = {}
    for node in nodes:
        rainfall_type = _text(node, "Type")
        if rainfall_type:
            values[rainfall_type] = _metric_value(node)
    return values


def _typed_values(nodes: Iterable[ET.Element]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for node in nodes:
        value_type = _text(node, "Type")
        if value_type:
            values[value_type] = _metric_value(node)
    return values


def _metric(parent: ET.Element, tag: str) -> float | None:
    node = parent.find(tag)
    return _metric_value(node) if node is not None else None


def _metric_value(node: ET.Element) -> float | None:
    return _float(_text(node, "dValue") or _text(node, "Value"))


def _metric_text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    return _text(node, "dValue") or _text(node, "Value")


def _text(parent: ET.Element | None, tag: str) -> str | None:
    if parent is None:
        return None
    node = parent.find(tag)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M")
