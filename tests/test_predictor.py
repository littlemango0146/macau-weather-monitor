from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.main import create_app
from app.predictor import predict_next_days, train


def write_sample_history(path, days: int = 90) -> None:
    start = date(2026, 1, 1)
    rows = []
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    for i in range(days):
        day = start + timedelta(days=i)
        warm_cycle = (i % 14) * 0.25
        rain = 0.0 if i % 4 else 4.0 + (i % 5)
        rows.append(
            {
                "date": day.isoformat(),
                "pressure_hpa": 1018 - (i % 9) * 0.4,
                "temp_max": 21 + warm_cycle + (1 if rain == 0 else -0.5),
                "temp_avg": 18 + warm_cycle,
                "temp_min": 15 + warm_cycle,
                "dew_point": 12 + warm_cycle * 0.6,
                "humidity_pct": 65 + (15 if rain else i % 8),
                "sunshine_h": 8.0 if rain == 0 else 1.5,
                "wind_direction": directions[i % len(directions)],
                "wind_speed_kmh": 8 + (i % 6),
                "rainfall_mm": rain,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_train_and_predict_returns_three_future_days(monkeypatch, tmp_path):
    import app.predictor as predictor

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)

    monkeypatch.setattr(predictor, "date", FakeDate)
    csv_path = tmp_path / "history.csv"
    model_dir = tmp_path / "models"
    write_sample_history(csv_path)

    meta = train(csv_path=csv_path, model_dir=model_dir)
    forecast = predict_next_days(days=3, csv_path=csv_path, model_dir=model_dir)

    assert meta["forecast_days"] == 3
    assert len(forecast) == 3
    assert [item["day_index"] for item in forecast] == [1, 2, 3]
    assert [item["date"] for item in forecast] == ["2026-04-01", "2026-04-02", "2026-04-03"]
    for item in forecast:
        assert 0 <= item["rain_prob"] <= 1
        assert item["rainfall_mm"] >= 0
        assert item["temp_min"] <= item["temp_avg"] <= item["temp_max"]


def test_predict_forecast_api_defaults_to_three_days(monkeypatch, tmp_path):
    import app.main as main_module

    app = create_app(db_path=tmp_path / "weather.sqlite", start_scheduler=False)

    def fake_predict_next_days(days=3):
        return [{"day_index": i, "date": f"2026-04-0{i}"} for i in range(1, days + 1)]

    monkeypatch.setattr(main_module, "predict_next_days", fake_predict_next_days)
    monkeypatch.setattr(main_module, "model_metrics", lambda: {"forecast_days": 3})
    client = TestClient(app)

    response = client.get("/api/predict/forecast")

    assert response.status_code == 200
    assert len(response.json()["forecast"]) == 3
