from datetime import datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import WeatherReading


def seed(client_db):
    client_db.insert_readings([
        WeatherReading(
            station_code="TG",
            station_name="大潭山",
            record_time=datetime(2026, 5, 23, 14, 15),
            temperature=28.2,
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
    ])


def test_api_returns_stations_latest_history_rankings_and_health(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    seed(app.state.db)
    client = TestClient(app)

    stations = client.get("/api/stations")
    latest = client.get("/api/stations/TG/latest")
    history = client.get("/api/stations/TG/history", params={"metric": "temperature"})
    rankings = client.get("/api/rankings", params={"metric": "temperature"})
    health = client.get("/api/health")

    assert stations.status_code == 200
    assert latest.json()["station_code"] == "TG"
    assert history.json()["points"][0]["value"] == 28.2
    assert rankings.json()["items"][0]["station_code"] == "TG"
    assert health.json()["database"] == "ok"


def test_api_allows_file_origin_for_offline_live_refresh(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    client = TestClient(app)

    response = client.options(
        "/api/health",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_api_refresh_collects_latest_data(monkeypatch, tmp_path):
    import app.main as main_module

    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)

    def fake_collect(db):
        seed(db)
        return {"inserted_count": 1, "weather_status": "ok", "external": {"official_forecast": "ok"}}

    monkeypatch.setattr(main_module, "collect_all_once", fake_collect)
    client = TestClient(app)

    response = client.get("/api/refresh")

    assert response.status_code == 200
    assert response.json()["inserted_count"] == 1
    assert client.get("/api/stations/TG/latest").json()["station_code"] == "TG"


def test_partial_collection_still_refreshes_external_sources(monkeypatch, tmp_path):
    import app.collector as collector

    db = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False).state.db

    def fail_weather(db):
        db.log_fetch("error", 0, "weather failed")
        raise RuntimeError("weather failed")

    monkeypatch.setattr(collector, "collect_once", fail_weather)
    monkeypatch.setattr(collector, "refresh_external_sources", lambda db: {"official_forecast": "ok"})

    result = collector.collect_all_once(db, raise_on_weather_error=False)

    assert result["weather_status"] == "error"
    assert result["external"]["official_forecast"] == "ok"


def test_dashboard_extension_endpoints_return_weather_modules(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    seed(app.state.db)
    client = TestClient(app)

    wind = client.get("/api/wind-index")
    comfort = client.get("/api/comfort-index")
    warnings = client.get("/api/warnings")
    water = client.get("/api/water-level")
    air = client.get("/api/air-quality")
    database = client.get("/api/database-summary")
    official_forecast = client.get("/api/official-forecast")
    dashboard = client.get("/api/dashboard")

    assert wind.status_code == 200
    assert wind.json()["beaufort"]["level"] >= 0
    assert comfort.status_code == 200
    assert comfort.json()["hottest"]["station_code"] == "TG"
    assert warnings.status_code == 200
    assert warnings.json()["source"]
    assert water.json()["status"] == "pending_source"
    assert air.json()["status"] == "pending_source"
    assert database.json()["station_count"] == 1
    assert official_forecast.json()["status"] == "pending_source"
    assert dashboard.json()["official_forecast"]["status"] == "pending_source"
    assert "wind_index" in dashboard.json()


def test_weather_csv_export_returns_observation_rows(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    seed(app.state.db)
    client = TestClient(app)

    response = client.get("/api/export/weather.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "station_code,station_name,record_time" in response.text
    assert "TG" in response.text


def test_history_export_and_data_quality_endpoints(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    seed(app.state.db)
    client = TestClient(app)

    quality = client.get("/api/data-quality")
    history = client.get("/api/stations/TG/history", params={"metric": "temperature", "interval": 10})
    export = client.get("/api/export/history.csv", params={"code": "TG", "metric": "temperature", "interval": 10})

    assert quality.status_code == 200
    assert quality.json()["reading_count"] == 1
    assert history.status_code == 200
    assert history.json()["points"][0]["sample_count"] == 1
    assert export.status_code == 200
    assert "sample_count" in export.text


def test_warning_events_endpoint_returns_saved_events(tmp_path):
    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)
    app.state.db.insert_warning_events([
        {"type": "雷暴", "status": "inactive", "issued_at": "2026-05-22 02:30", "message": "現時沒有雷暴警告。"}
    ])
    client = TestClient(app)

    response = client.get("/api/warning-events")

    assert response.status_code == 200
    assert response.json()["items"][0]["warning_type"] == "雷暴"


def test_external_dashboard_uses_official_xml_parsers(monkeypatch, tmp_path):
    import app.external_sources as external_sources

    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False, external_sources=True)
    seed(app.state.db)

    seven_day = """
    <SevenDaysForecast>
      <System><SysPubdate>2026-05-23 17:00</SysPubdate></System>
      <Custom><WeatherForecast>
        <ValidFor>2026-05-24</ValidFor><c_DayOfWeek>日</c_DayOfWeek>
        <Temperature><Type>1</Type><Value>31</Value></Temperature>
        <Temperature><Type>2</Type><Value>27</Value></Temperature>
        <Humidity><Type>1</Type><Value>95</Value></Humidity>
        <Humidity><Type>2</Type><Value>70</Value></Humidity>
        <WeatherDescription>多雲。</WeatherDescription>
      </WeatherForecast></Custom>
    </SevenDaysForecast>
    """.encode()
    air = """
    <ForecastIQA>
      <System><SysPubdate>2026-05-23 17:30:26</SysPubdate></System>
      <Custom><AQIForecastReport><Station code="BDR"><Stationname>路邊</Stationname>
        <AQIForecast><ValidFor>2026-05-24</ValidFor><Value>30-50</Value>
        <AQIForecastDescription>良好</AQIForecastDescription></AQIForecast>
      </Station></AQIForecastReport></Custom>
    </ForecastIQA>
    """.encode()
    warning = """
    <RainstormWarning>
      <System><SysPubdate>2026-05-22 02:30 GMT+8</SysPubdate></System>
      <Custom><Rainstorm><Inforce>0</Inforce><Status>0</Status>
        <IssuedAt>2026-05-22 02:30</IssuedAt><Description>現時沒有暴雨警告信號。</Description>
      </Rainstorm></Custom>
    </RainstormWarning>
    """.encode()

    def fake_fetch(url, timeout=8):
      if "7daysforecast" in url:
          return seven_day
      if "foreiqa" in url:
          return air
      return warning

    monkeypatch.setattr(external_sources, "fetch_xml", fake_fetch)
    external_sources.refresh_external_sources(app.state.db)
    client = TestClient(app)

    data = client.get("/api/dashboard").json()

    assert data["official_forecast"]["status"] == "active"
    assert data["official_forecast"]["items"][0]["temp_high"] == 31
    assert data["air_quality"]["items"][0]["station_code"] == "BDR"
    assert data["warnings"]["official_status"] == "active"
