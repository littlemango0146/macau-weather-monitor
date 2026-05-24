from __future__ import annotations

from contextlib import asynccontextmanager
import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .collector import collect_all_once
from .dashboard import (
    air_quality_summary,
    comfort_index,
    database_summary,
    official_forecast_summary,
    warning_summary,
    water_level_summary,
    wind_index,
)
from .db import WeatherDatabase, validate_metric
from .predictor import train as ml_train, predict_next_days, model_metrics
from .scheduler import CollectorScheduler
from .stations import STATIONS_BY_CODE, station_list


def create_app(
    db_path: str | Path = "data/weather.sqlite",
    start_scheduler: bool = True,
    external_sources: bool = False,
) -> FastAPI:
    db = WeatherDatabase(db_path)
    db.init()
    scheduler = CollectorScheduler(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db
        app.state.scheduler = scheduler
        if start_scheduler:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(title="澳門氣象資料站", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.db = db
    app.state.scheduler = scheduler

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/predict")
    def predict_page():
        return FileResponse(static_dir / "predict.html")

    @app.get("/api/stations")
    def api_stations():
        latest = db.latest_by_station()
        return [
            {
                **station,
                "latest": latest.get(station["code"]),
            }
            for station in station_list()
        ]

    @app.get("/api/stations/latest")
    def api_latest_stations():
        latest = db.latest_by_station()
        return {"items": list(latest.values()), "fetch": db.latest_fetch(), "latest_success": db.latest_success()}

    @app.get("/api/stations/{code}/latest")
    def api_station_latest(code: str):
        row = db.latest_for_station(code)
        if not row:
            raise HTTPException(status_code=404, detail="找不到此站點的觀測資料")
        station = STATIONS_BY_CODE.get(code.upper())
        return {**row, "station": station}

    @app.get("/api/stations/{code}/history")
    def api_station_history(
        code: str,
        metric: str = Query("temperature"),
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        interval: int | None = Query(None, ge=5, le=60),
    ):
        try:
            points = (
                db.history_aggregated(code, metric, from_, to, interval)
                if interval
                else db.history(code, metric, from_, to)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"station_code": code.upper(), "metric": metric, "points": points}

    @app.get("/api/rankings")
    def api_rankings(metric: str = Query("temperature")):
        try:
            validate_metric(metric)
            items = db.ranking(metric)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"metric": metric, "items": items}

    @app.get("/api/refresh")
    def api_refresh():
        try:
            result = collect_all_once(db)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"抓取澳門氣象局資料失敗：{exc}") from exc
        return {
            "status": "ok",
            "inserted_count": result["inserted_count"],
            "weather_status": result["weather_status"],
            "external": result["external"],
            "latest_success": db.latest_success(),
        }

    @app.get("/api/health")
    def api_health():
        return {
            "database": "ok" if db.path.exists() else "missing",
            "latest_fetch": db.latest_fetch(),
            "latest_success": db.latest_success(),
            "latest_data_time": db.latest_data_time(),
        }

    @app.get("/api/data-quality")
    def api_data_quality():
        latest_by_station = db.latest_station_times()
        latest_data_time = db.latest_data_time()
        delay_minutes = None
        if latest_data_time:
            try:
                delay_minutes = round((datetime.now() - datetime.fromisoformat(latest_data_time)).total_seconds() / 60, 1)
            except ValueError:
                delay_minutes = None
        missing = [station for station in station_list() if station["code"] not in latest_by_station]
        stale = []
        for station in station_list():
            record_time = latest_by_station.get(station["code"])
            if not record_time:
                continue
            try:
                station_delay = (datetime.now() - datetime.fromisoformat(record_time)).total_seconds() / 60
            except ValueError:
                continue
            if station_delay > 30:
                stale.append({**station, "record_time": record_time, "delay_minutes": round(station_delay, 1)})
        return {
            "latest_data_time": latest_data_time,
            "delay_minutes": delay_minutes,
            "reading_count": db.count_readings(),
            "station_count": len(latest_by_station),
            "expected_station_count": len(station_list()),
            "missing_stations": missing,
            "stale_stations": stale,
            "external_sources": db.list_external_cache(),
            "latest_fetch": db.latest_fetch(),
            "latest_success": db.latest_success(),
        }

    @app.get("/api/warning-events")
    def api_warning_events(limit: int = Query(50, ge=1, le=200)):
        return {"items": db.list_warning_events(limit)}

    @app.get("/api/compare")
    def api_compare(
        codes: str = Query(..., description="逗號分隔的站碼，例如 TG,FM,DP"),
        metric: str = Query("temperature"),
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
    ):
        code_list = [c.strip().upper() for c in codes.split(",") if c.strip()]
        if not code_list:
            raise HTTPException(status_code=400, detail="請提供至少一個站碼")
        try:
            data = db.compare(code_list, metric, from_, to)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"metric": metric, "series": data}

    @app.get("/api/export/history.csv")
    def api_export_history_csv(
        code: str = Query(...),
        metric: str = Query("temperature"),
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        interval: int | None = Query(None, ge=5, le=60),
    ):
        try:
            rows = (
                db.history_aggregated(code, metric, from_, to, interval)
                if interval
                else db.history(code, metric, from_, to, limit=100000)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        output = io.StringIO()
        fieldnames = ["record_time", "value"]
        if rows and "sample_count" in rows[0]:
            fieldnames.extend(["min_value", "max_value", "sample_count"])
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{code.upper()}-{metric}.csv"'},
        )

    @app.get("/api/daily-summary")
    def api_daily_summary():
        return db.daily_summary()

    @app.get("/api/wind-index")
    def api_wind_index():
        return wind_index(db.latest_by_station())

    @app.get("/api/comfort-index")
    def api_comfort_index():
        return comfort_index(db.latest_by_station())

    @app.get("/api/warnings")
    def api_warnings():
        return warning_summary(db.latest_by_station(), db=db, fetch_live=False)

    @app.get("/api/water-level")
    def api_water_level():
        return water_level_summary()

    @app.get("/api/air-quality")
    def api_air_quality():
        return air_quality_summary(db=db, fetch_live=False)

    @app.get("/api/database-summary")
    def api_database_summary():
        return database_summary(db)

    @app.get("/api/official-forecast")
    def api_official_forecast():
        return official_forecast_summary(db=db, fetch_live=False)

    @app.get("/api/dashboard")
    def api_dashboard():
        latest = db.latest_by_station()
        return {
            "wind_index": wind_index(latest),
            "comfort_index": comfort_index(latest),
            "warnings": warning_summary(latest, db=db, fetch_live=False),
            "water_level": water_level_summary(),
            "air_quality": air_quality_summary(db=db, fetch_live=False),
            "database": database_summary(db),
            "official_forecast": official_forecast_summary(db=db, fetch_live=False),
        }

    @app.get("/api/export/weather.csv")
    def api_export_weather_csv(
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        limit: int = Query(10000, ge=1, le=100000),
    ):
        rows = db.export_readings(from_, to, limit)
        output = io.StringIO()
        fieldnames = [
            "station_code", "station_name", "record_time", "temperature", "humidity",
            "dew_point", "wind_gust", "wind_speed", "rainfall_current", "rainfall_hour",
            "rainfall_day", "wind_direction", "wind_degree", "wind_description",
            "mean_sea_level_pressure", "station_pressure",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="macau-weather.csv"'},
        )

    # ── 預測 API ──────────────────────────────
    @app.get("/api/predict/train")
    def api_predict_train():
        """觸發模型訓練（可能需 10–30 秒）"""
        try:
            meta = ml_train()
            return {"status": "ok", "meta": meta}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/predict/forecast")
    def api_predict_forecast(days: int = Query(3, ge=1, le=3)):
        """回傳未來 N 天預測（需先訓練）"""
        try:
            result = predict_next_days(days=days)
            return {"status": "ok", "forecast": result, "metrics": model_metrics()}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/predict/metrics")
    def api_predict_metrics():
        """回傳模型評估指標"""
        m = model_metrics()
        if not m:
            raise HTTPException(status_code=404, detail="模型尚未訓練")
        return m

    @app.get("/api/predict/update-data")
    def api_update_data():
        """從 SMG 增量補齊最近天氣資料，並重新訓練模型"""
        import subprocess, sys
        script = Path(__file__).parent.parent / "scripts" / "scrape_smg.py"
        try:
            result = subprocess.run(
                [sys.executable, str(script), "--delay", "0.5"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=result.stderr[-500:])
            meta = ml_train()
            return {"status": "ok", "scrape_log": result.stdout[-1000:], "model": meta}
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=503, detail="爬取超時（>5 分鐘）")

    return app


app = create_app(start_scheduler=True, external_sources=True)
