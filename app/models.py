from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class WeatherReading:
    station_code: str
    station_name: str
    record_time: datetime
    temperature: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    wind_gust: float | None = None
    wind_speed: float | None = None
    rainfall_current: float | None = None
    rainfall_hour: float | None = None
    rainfall_day: float | None = None
    wind_direction: str | None = None
    wind_degree: float | None = None
    wind_description: str | None = None
    mean_sea_level_pressure: float | None = None
    station_pressure: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["record_time"] = self.record_time.isoformat()
        return data
