from __future__ import annotations


STATIONS: list[dict] = [
    {"code": "DP", "name": "紀念孫中山市政公園", "region": "澳門半島", "lat": 22.2148, "lon": 113.5517, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "EM", "name": "黑沙環", "region": "澳門半島", "lat": 22.2082, "lon": 113.5536, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "FM", "name": "大炮台", "region": "澳門半島", "lat": 22.1975, "lon": 113.5409, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PE", "name": "外港", "region": "澳門半島", "lat": 22.1962, "lon": 113.5588, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "MM", "name": "媽閣", "region": "澳門半島", "lat": 22.1867, "lon": 113.5294, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "TG", "name": "大潭山", "region": "氹仔", "lat": 22.1592, "lon": 113.5767, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "JA", "name": "東亞運大馬路", "region": "氹仔", "lat": 22.1425, "lon": 113.5635, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "KV", "name": "九澳", "region": "路環", "lat": 22.1238, "lon": 113.5861, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "UM", "name": "澳門大學", "region": "橫琴澳大", "lat": 22.1265, "lon": 113.5457, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "DC", "name": "路環市區", "region": "路環", "lat": 22.1136, "lon": 113.5558, "has_full_weather": True, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "MN", "name": "澳門大橋北", "region": "橋上", "lat": 22.1895, "lon": 113.5638, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "MS", "name": "澳門大橋南", "region": "橋上", "lat": 22.1639, "lon": 113.5752, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PN", "name": "友誼大橋北", "region": "橋上", "lat": 22.2021, "lon": 113.5636, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PS", "name": "友誼大橋南", "region": "橋上", "lat": 22.1665, "lon": 113.5754, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PG", "name": "嘉樂庇總督大橋", "region": "橋上", "lat": 22.1791, "lon": 113.5567, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PV", "name": "西灣大橋", "region": "橋上", "lat": 22.1701, "lon": 113.5416, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
    {"code": "PL", "name": "蓮花大橋", "region": "路氹", "lat": 22.1364, "lon": 113.5362, "has_full_weather": False, "coordinate_source": "manual_osm", "coordinate_precision": "approx"},
]

STATIONS_BY_CODE = {station["code"]: station for station in STATIONS}


def station_list() -> list[dict]:
    return [station.copy() for station in STATIONS]


def station_for_code(code: str) -> dict | None:
    station = STATIONS_BY_CODE.get(code.upper())
    return station.copy() if station else None
