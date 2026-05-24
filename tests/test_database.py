from datetime import datetime

from app.db import WeatherDatabase
from app.models import WeatherReading


def make_reading(value: float = 28.2) -> WeatherReading:
    return WeatherReading(
        station_code="TG",
        station_name="大潭山",
        record_time=datetime(2026, 5, 23, 14, 15),
        temperature=value,
        humidity=88,
        dew_point=26,
        wind_gust=26.6,
        wind_speed=13.3,
        rainfall_current=0.0,
        rainfall_hour=1.2,
        rainfall_day=8.4,
        wind_direction="S",
        wind_degree=175,
        wind_description="南",
        mean_sea_level_pressure=1008.9,
        station_pressure=996.1,
    )


def test_insert_readings_deduplicates_station_and_record_time(tmp_path):
    db = WeatherDatabase(tmp_path / "weather.sqlite")
    db.init()

    inserted_first = db.insert_readings([make_reading(28.2)])
    inserted_second = db.insert_readings([make_reading(29.0)])

    assert inserted_first == 1
    assert inserted_second == 0
    assert len(db.history("TG", "temperature")) == 1
    assert db.latest_by_station()["TG"]["temperature"] == 28.2


def test_rankings_order_numeric_metric_descending(tmp_path):
    db = WeatherDatabase(tmp_path / "weather.sqlite")
    db.init()
    first = make_reading(28.2)
    second = make_reading(30.0)
    second.station_code = "FM"
    second.station_name = "大炮台"

    db.insert_readings([first, second])

    ranking = db.ranking("temperature")

    assert [row["station_code"] for row in ranking] == ["FM", "TG"]


def test_external_cache_round_trips_json_payload(tmp_path):
    db = WeatherDatabase(tmp_path / "weather.sqlite")
    db.init()

    db.upsert_external_cache(
        "official_forecast",
        "https://xml.smg.gov.mo/c_7daysforecast.xml",
        "active",
        {"status": "active", "items": [{"valid_for": "2026-05-24", "temp_high": 31}]},
    )

    cached = db.get_external_cache("official_forecast")

    assert cached["status"] == "active"
    assert cached["items"][0]["temp_high"] == 31
    assert cached["cache_updated_at"]


def test_history_aggregated_groups_points_by_interval(tmp_path):
    db = WeatherDatabase(tmp_path / "weather.sqlite")
    db.init()
    first = make_reading(28.0)
    second = make_reading(30.0)
    second.record_time = datetime(2026, 5, 23, 14, 19)
    third = make_reading(32.0)
    third.record_time = datetime(2026, 5, 23, 14, 31)
    db.insert_readings([first, second, third])

    rows = db.history_aggregated("TG", "temperature", interval_minutes=30)

    assert len(rows) == 2
    assert rows[0]["value"] == 29.0
    assert rows[0]["sample_count"] == 2


def test_warning_events_are_deduplicated(tmp_path):
    db = WeatherDatabase(tmp_path / "weather.sqlite")
    db.init()
    event = {"type": "暴雨", "status": "inactive", "issued_at": "2026-05-22 02:30", "message": "現時沒有暴雨警告。"}

    first = db.insert_warning_events([event])
    second = db.insert_warning_events([event])

    assert first == 1
    assert second == 0
    assert db.list_warning_events()[0]["warning_type"] == "暴雨"
