from __future__ import annotations

import shutil
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import WeatherReading

METRICS = {
    "temperature",
    "humidity",
    "dew_point",
    "wind_gust",
    "wind_speed",
    "rainfall_current",
    "rainfall_hour",
    "rainfall_day",
    "wind_degree",
    "mean_sea_level_pressure",
    "station_pressure",
}


class WeatherDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    station_code TEXT NOT NULL,
                    station_name TEXT NOT NULL,
                    record_time TEXT NOT NULL,
                    temperature REAL,
                    humidity REAL,
                    dew_point REAL,
                    wind_gust REAL,
                    wind_speed REAL,
                    rainfall_current REAL,
                    rainfall_hour REAL,
                    rainfall_day REAL,
                    wind_direction TEXT,
                    wind_degree REAL,
                    wind_description TEXT,
                    mean_sea_level_pressure REAL,
                    station_pressure REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (station_code, record_time)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_readings_station_time ON readings (station_code, record_time)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_time ON readings (record_time)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fetch_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    inserted_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS external_cache (
                    cache_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS warning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    warning_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    issued_at TEXT,
                    updated_at TEXT NOT NULL,
                    message TEXT,
                    source TEXT,
                    UNIQUE (warning_type, status, issued_at, message)
                )
                """
            )

    def insert_readings(self, readings: list[WeatherReading]) -> int:
        if not readings:
            return 0
        with self._connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO readings (
                    station_code, station_name, record_time, temperature, humidity, dew_point,
                    wind_gust, wind_speed, rainfall_current, rainfall_hour, rainfall_day,
                    wind_direction, wind_degree, wind_description, mean_sea_level_pressure, station_pressure
                )
                VALUES (
                    :station_code, :station_name, :record_time, :temperature, :humidity, :dew_point,
                    :wind_gust, :wind_speed, :rainfall_current, :rainfall_hour, :rainfall_day,
                    :wind_direction, :wind_degree, :wind_description, :mean_sea_level_pressure, :station_pressure
                )
                """,
                [reading.to_dict() for reading in readings],
            )
            return conn.total_changes - before

    def log_fetch(self, status: str, inserted_count: int = 0, message: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fetch_log (fetched_at, status, inserted_count, message) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), status, inserted_count, message),
            )

    def latest_fetch(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at, status, inserted_count, message FROM fetch_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def latest_data_time(self) -> str | None:
        """最新一筆觀測資料的 record_time（SMG 的觀測時間，非抓取時間）"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(record_time) AS t FROM readings"
            ).fetchone()
            return row["t"] if row else None

    def latest_success(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT fetched_at, status, inserted_count, message
                FROM fetch_log
                WHERE status = 'ok'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def upsert_external_cache(
        self,
        cache_key: str,
        source: str,
        status: str,
        payload: dict[str, Any],
        error: str | None = None,
    ) -> None:
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO external_cache (cache_key, source, status, updated_at, payload_json, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    source = excluded.source,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json,
                    error = excluded.error
                """,
                (cache_key, source, status, updated_at, json.dumps(payload, ensure_ascii=False), error),
            )

    def get_external_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT cache_key, source, status, updated_at, payload_json, error
                FROM external_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            payload = json.loads(data.pop("payload_json"))
            payload.setdefault("source", data["source"])
            payload.setdefault("status", data["status"])
            payload["cache_updated_at"] = data["updated_at"]
            if data.get("error"):
                payload["error"] = data["error"]
            return payload

    def latest_by_station(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*
                FROM readings r
                JOIN (
                    SELECT station_code, MAX(record_time) AS record_time
                    FROM readings
                    GROUP BY station_code
                ) latest
                ON latest.station_code = r.station_code AND latest.record_time = r.record_time
                ORDER BY r.station_code
                """
            ).fetchall()
            return {row["station_code"]: dict(row) for row in rows}

    def latest_for_station(self, station_code: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM readings
                WHERE station_code = ?
                ORDER BY record_time DESC
                LIMIT 1
                """,
                (station_code.upper(),),
            ).fetchone()
            return dict(row) if row else None

    def history(
        self,
        station_code: str,
        metric: str,
        from_time: str | None = None,
        to_time: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        metric = validate_metric(metric)
        clauses = ["station_code = ?", f"{metric} IS NOT NULL"]
        params: list[Any] = [station_code.upper()]
        if from_time:
            clauses.append("record_time >= ?")
            params.append(from_time)
        if to_time:
            clauses.append("record_time <= ?")
            params.append(to_time)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT record_time, {metric} AS value
                FROM readings
                WHERE {" AND ".join(clauses)}
                ORDER BY record_time ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def history_aggregated(
        self,
        station_code: str,
        metric: str,
        from_time: str | None = None,
        to_time: str | None = None,
        interval_minutes: int = 10,
        limit: int = 3000,
    ) -> list[dict[str, Any]]:
        metric = validate_metric(metric)
        if interval_minutes not in {5, 10, 30, 60}:
            raise ValueError("Unsupported interval. Allowed intervals: 5, 10, 30, 60")
        clauses = ["station_code = ?", f"{metric} IS NOT NULL"]
        where_params: list[Any] = [station_code.upper()]
        if from_time:
            clauses.append("record_time >= ?")
            where_params.append(from_time)
        if to_time:
            clauses.append("record_time <= ?")
            where_params.append(to_time)
        params: list[Any] = [interval_minutes, interval_minutes, *where_params]
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                WITH bucketed AS (
                    SELECT
                        datetime(
                            strftime('%Y-%m-%d %H:', record_time) ||
                            printf('%02d', (CAST(strftime('%M', record_time) AS INTEGER) / ?) * ?) ||
                            ':00'
                        ) AS bucket_time,
                        {metric} AS value
                    FROM readings
                    WHERE {" AND ".join(clauses)}
                )
                SELECT
                    bucket_time AS record_time,
                    AVG(value) AS value,
                    MIN(value) AS min_value,
                    MAX(value) AS max_value,
                    COUNT(value) AS sample_count
                FROM bucketed
                GROUP BY bucket_time
                ORDER BY bucket_time ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def ranking(self, metric: str) -> list[dict]:
        metric = validate_metric(metric)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT r.station_code, r.station_name, r.record_time, r.{metric} AS value
                FROM readings r
                JOIN (
                    SELECT station_code, MAX(record_time) AS record_time
                    FROM readings
                    WHERE {metric} IS NOT NULL
                    GROUP BY station_code
                ) latest
                ON latest.station_code = r.station_code AND latest.record_time = r.record_time
                WHERE r.{metric} IS NOT NULL
                ORDER BY r.{metric} DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def compare(
        self,
        station_codes: list[str],
        metric: str,
        from_time: str | None = None,
        to_time: str | None = None,
        limit: int = 2000,
    ) -> dict[str, list[dict]]:
        metric = validate_metric(metric)
        result: dict[str, list[dict]] = {}
        for code in station_codes:
            clauses = ["station_code = ?", f"{metric} IS NOT NULL"]
            params: list[Any] = [code.upper()]
            if from_time:
                clauses.append("record_time >= ?")
                params.append(from_time)
            if to_time:
                clauses.append("record_time <= ?")
                params.append(to_time)
            params.append(limit)
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT record_time, {metric} AS value
                    FROM readings
                    WHERE {" AND ".join(clauses)}
                    ORDER BY record_time ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                result[code.upper()] = [dict(row) for row in rows]
        return result

    def daily_summary(self) -> dict:
        """今日（本地日期）各指標統計：最高/最低/平均"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    MAX(temperature) AS max_temp,
                    MIN(temperature) AS min_temp,
                    AVG(temperature) AS avg_temp,
                    MAX(humidity)    AS max_humidity,
                    MIN(humidity)    AS min_humidity,
                    AVG(humidity)    AS avg_humidity,
                    MAX(wind_gust)   AS max_gust,
                    MAX(wind_speed)  AS max_wind,
                    MAX(mean_sea_level_pressure) AS max_pressure,
                    MIN(mean_sea_level_pressure) AS min_pressure,
                    AVG(mean_sea_level_pressure) AS avg_pressure
                FROM readings
                WHERE record_time >= ?
                """,
                (today,),
            ).fetchone()
            daily = dict(row) if row else {}

            # 今日最高累計雨量（取各站 MAX(rainfall_day) 中的最大值）
            rain_row = conn.execute(
                """
                SELECT MAX(rainfall_day) AS max_rain_day
                FROM readings
                WHERE record_time >= ?
                  AND rainfall_day IS NOT NULL
                """,
                (today,),
            ).fetchone()
            daily["max_rain_day"] = (rain_row["max_rain_day"] if rain_row else None)

            # 最高溫所在站點
            max_temp_row = conn.execute(
                """
                SELECT station_name, record_time, temperature
                FROM readings
                WHERE record_time >= ? AND temperature IS NOT NULL
                ORDER BY temperature DESC LIMIT 1
                """,
                (today,),
            ).fetchone()
            daily["max_temp_station"] = max_temp_row["station_name"] if max_temp_row else None

            # 最低溫所在站點
            min_temp_row = conn.execute(
                """
                SELECT station_name, record_time, temperature
                FROM readings
                WHERE record_time >= ? AND temperature IS NOT NULL
                ORDER BY temperature ASC LIMIT 1
                """,
                (today,),
            ).fetchone()
            daily["min_temp_station"] = min_temp_row["station_name"] if min_temp_row else None

            return daily

    def export_readings(
        self,
        from_time: str | None = None,
        to_time: str | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if from_time:
            clauses.append("record_time >= ?")
            params.append(from_time)
        if to_time:
            clauses.append("record_time <= ?")
            params.append(to_time)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT station_code, station_name, record_time, temperature, humidity, dew_point,
                       wind_gust, wind_speed, rainfall_current, rainfall_hour, rainfall_day,
                       wind_direction, wind_degree, wind_description, mean_sea_level_pressure,
                       station_pressure
                FROM readings
                {where}
                ORDER BY record_time DESC, station_code ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def count_readings(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM readings").fetchone()
            return int(row["count"] or 0)

    def latest_station_times(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT station_code, MAX(record_time) AS record_time
                FROM readings
                GROUP BY station_code
                """
            ).fetchall()
            return {row["station_code"]: row["record_time"] for row in rows}

    def list_external_cache(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT cache_key, source, status, updated_at, error
                FROM external_cache
                ORDER BY cache_key
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def insert_warning_events(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (
                item.get("type") or "unknown",
                item.get("status") or "unknown",
                item.get("issued_at"),
                now,
                item.get("message"),
                item.get("source"),
            )
            for item in items
        ]
        with self._connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO warning_events
                    (warning_type, status, issued_at, updated_at, message, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return conn.total_changes - before

    def list_warning_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT warning_type, status, issued_at, updated_at, message, source
                FROM warning_events
                ORDER BY COALESCE(issued_at, updated_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def backup(self, backup_dir: str | Path = "backups") -> Path:
        target_dir = Path(backup_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"weather-{stamp}.sqlite"
        shutil.copy2(self.path, target)
        return target

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def validate_metric(metric: str) -> str:
    if metric not in METRICS:
        allowed = ", ".join(sorted(METRICS))
        raise ValueError(f"Unsupported metric '{metric}'. Allowed metrics: {allowed}")
    return metric
