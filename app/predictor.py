from __future__ import annotations

import json
import os
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")
warnings.filterwarnings(
    "ignore",
    message="Could not find the number of physical cores.*",
    category=UserWarning,
)

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

ROOT = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "smg_history.csv"
MODEL_DIR = ROOT / "data" / "models"
FORECAST_DAYS = 3

REGRESSION_TARGETS = {
    "temp_max": "最高溫",
    "temp_avg": "平均溫",
    "temp_min": "最低溫",
    "humidity_pct": "濕度",
    "wind_speed_kmh": "平均風速",
    "rainfall_mm": "雨量",
}
CLASSIFICATION_TARGETS = {"rain_yn": "降雨機率"}
ALL_TARGETS = tuple(REGRESSION_TARGETS) + tuple(CLASSIFICATION_TARGETS)

NUMERIC_COLUMNS = [
    "pressure_hpa",
    "temp_max",
    "temp_avg",
    "temp_min",
    "dew_point",
    "humidity_pct",
    "sunshine_h",
    "wind_speed_kmh",
    "rainfall_mm",
]

COMPASS_DEGREES = {
    "N": 0,
    "NNE": 22.5,
    "NE": 45,
    "ENE": 67.5,
    "E": 90,
    "ESE": 112.5,
    "SE": 135,
    "SSE": 157.5,
    "S": 180,
    "SSW": 202.5,
    "SW": 225,
    "WSW": 247.5,
    "W": 270,
    "WNW": 292.5,
    "NW": 315,
    "NNW": 337.5,
    "C": 0,
    "CALM": 0,
    "VRB": 0,
}


def _model_dir(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else MODEL_DIR


def _wind_degree(value: Any) -> float:
    parts = str(value or "").upper().replace("/", " ").split()
    degrees = [COMPASS_DEGREES[p] for p in parts if p in COMPASS_DEGREES]
    if not degrees:
        return 0.0
    radians = np.deg2rad(degrees)
    x = np.sin(radians).mean()
    y = np.cos(radians).mean()
    return float((np.rad2deg(np.arctan2(x, y)) + 360) % 360)


def load_history(csv_path: str | Path = CSV_PATH) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].ffill().bfill().fillna(0)

    df["rainfall_mm"] = df["rainfall_mm"].clip(lower=0)
    df["rain_yn"] = (df["rainfall_mm"] > 0).astype(int)
    df["wind_degree"] = df["wind_direction"].map(_wind_degree)
    radians = np.deg2rad(df["wind_degree"])
    df["wind_sin"] = np.sin(radians)
    df["wind_cos"] = np.cos(radians)
    return df


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    doy = frame["date"].dt.dayofyear
    frame["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    frame["month_sin"] = np.sin(2 * np.pi * frame["date"].dt.month / 12)
    frame["month_cos"] = np.cos(2 * np.pi * frame["date"].dt.month / 12)

    lag_columns = NUMERIC_COLUMNS + ["rain_yn", "wind_sin", "wind_cos"]
    for col in lag_columns:
        for lag in (1, 2, 3, 7, 14):
            frame[f"{col}_lag{lag}"] = frame[col].shift(lag)

    for col in ("temp_avg", "humidity_pct", "pressure_hpa", "wind_speed_kmh", "rainfall_mm"):
        for window in (3, 7, 14):
            shifted = frame[col].shift(1)
            frame[f"{col}_roll{window}_mean"] = shifted.rolling(window).mean()
            frame[f"{col}_roll{window}_std"] = shifted.rolling(window).std()

    frame = frame.copy()
    frame["pressure_change_24h"] = frame["pressure_hpa"] - frame["pressure_hpa"].shift(1)
    frame["temp_range"] = frame["temp_max"] - frame["temp_min"]
    frame["dew_spread"] = frame["temp_avg"] - frame["dew_point"]
    return frame.dropna().reset_index(drop=True)


def extend_history_to_today(history: pd.DataFrame) -> pd.DataFrame:
    today = pd.Timestamp(date.today())
    latest = history["date"].max()
    if latest >= today:
        return history

    base = history.copy()
    base["_month"] = base["date"].dt.month
    base["_day"] = base["date"].dt.day
    climatology = base.groupby(["_month", "_day"])[NUMERIC_COLUMNS].mean()
    wind_climatology = base.groupby(["_month", "_day"])["wind_direction"].agg(
        lambda values: values.mode().iloc[0] if not values.mode().empty else "N"
    )

    rows = []
    current = latest
    fallback_numeric = base[NUMERIC_COLUMNS].tail(30).mean()
    fallback_wind = base["wind_direction"].tail(30).mode()
    fallback_wind_value = fallback_wind.iloc[0] if not fallback_wind.empty else "N"

    while current < today:
        current = current + timedelta(days=1)
        key = (current.month, current.day)
        row = base.iloc[-1].copy()
        row["date"] = current
        if key in climatology.index:
            for col in NUMERIC_COLUMNS:
                row[col] = climatology.loc[key, col]
        else:
            for col in NUMERIC_COLUMNS:
                row[col] = fallback_numeric[col]
        row["wind_direction"] = wind_climatology.loc[key] if key in wind_climatology.index else fallback_wind_value
        rows.append(row.drop(labels=["_month", "_day"], errors="ignore"))

    if rows:
        history = pd.concat([history, pd.DataFrame(rows)], ignore_index=True)

    history["rainfall_mm"] = pd.to_numeric(history["rainfall_mm"], errors="coerce").fillna(0).clip(lower=0)
    history["rain_yn"] = (history["rainfall_mm"] > 0).astype(int)
    history["wind_degree"] = history["wind_direction"].map(_wind_degree)
    radians = np.deg2rad(history["wind_degree"])
    history["wind_sin"] = np.sin(radians)
    history["wind_cos"] = np.cos(radians)
    return history.drop(columns=["_month", "_day"], errors="ignore").reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {"date", "wind_direction", "wind_degree"} | set(ALL_TARGETS)
    return [col for col in frame.columns if col not in excluded]


def _regressor() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=0.06,
        max_iter=220,
        max_leaf_nodes=24,
        l2_regularization=0.05,
        random_state=42,
    )


def _classifier() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.06,
        max_iter=180,
        max_leaf_nodes=20,
        l2_regularization=0.05,
        random_state=42,
    )


def _time_series_scores(model, X: pd.DataFrame, y: pd.Series, kind: str) -> dict[str, float]:
    if len(X) < 80:
        return {}

    splitter = TimeSeriesSplit(n_splits=4)
    maes: list[float] = []
    rmses: list[float] = []
    accuracies: list[float] = []
    aucs: list[float] = []

    for train_idx, val_idx in splitter.split(X):
        estimator = clone(model)
        y_train = y.iloc[train_idx]
        y_val = y.iloc[val_idx]
        if kind == "cls" and y_train.nunique() < 2:
            estimator = DummyClassifier(strategy="most_frequent")
        estimator.fit(X.iloc[train_idx], y_train)
        pred = estimator.predict(X.iloc[val_idx])

        if kind == "reg":
            maes.append(mean_absolute_error(y_val, pred))
            rmses.append(mean_squared_error(y_val, pred) ** 0.5)
        else:
            accuracies.append(accuracy_score(y_val, pred))
            if hasattr(estimator, "predict_proba") and y_val.nunique() > 1:
                aucs.append(roc_auc_score(y_val, estimator.predict_proba(X.iloc[val_idx])[:, 1]))

    if kind == "reg":
        return {
            "mae": round(float(np.mean(maes)), 3),
            "rmse": round(float(np.mean(rmses)), 3),
        }
    return {
        "accuracy": round(float(np.mean(accuracies)), 3),
        "auc": round(float(np.mean(aucs)), 3) if aucs else 0.0,
    }


def train(csv_path: str | Path = CSV_PATH, model_dir: str | Path | None = None) -> dict[str, Any]:
    out_dir = _model_dir(model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    history = load_history(csv_path)
    frame = build_feature_frame(history)
    columns = feature_columns(frame)
    metrics: dict[str, Any] = {}

    for horizon in range(1, FORECAST_DAYS + 1):
        horizon_key = f"day_{horizon}"
        metrics[horizon_key] = {}
        usable = frame.iloc[:-horizon].copy()
        X = usable[columns]

        for target in REGRESSION_TARGETS:
            y = frame[target].shift(-horizon).dropna().iloc[-len(usable):].reset_index(drop=True)
            model = _regressor()
            metrics[horizon_key][target] = _time_series_scores(model, X.reset_index(drop=True), y, "reg")
            model.fit(X, y)
            joblib.dump(model, out_dir / f"h{horizon}_{target}.joblib")

        y_rain = frame["rain_yn"].shift(-horizon).dropna().iloc[-len(usable):].astype(int).reset_index(drop=True)
        classifier = _classifier() if y_rain.nunique() > 1 else DummyClassifier(strategy="most_frequent")
        metrics[horizon_key]["rain_yn"] = _time_series_scores(
            classifier, X.reset_index(drop=True), y_rain, "cls"
        )
        classifier.fit(X, y_rain)
        joblib.dump(classifier, out_dir / f"h{horizon}_rain_yn.joblib")

    meta = {
        "model": "HistGradientBoosting direct multi-horizon",
        "forecast_days": FORECAST_DAYS,
        "feature_cols": columns,
        "targets": {**REGRESSION_TARGETS, **CLASSIFICATION_TARGETS},
        "metrics": metrics,
        "trained_on": date.today().isoformat(),
        "history_start": history["date"].min().date().isoformat(),
        "history_end": history["date"].max().date().isoformat(),
        "n_samples": int(len(frame)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _latest_features(csv_path: str | Path, meta: dict[str, Any]) -> tuple[pd.DataFrame, pd.Timestamp]:
    history = extend_history_to_today(load_history(csv_path))
    frame = build_feature_frame(history)
    X = frame[meta["feature_cols"]].iloc[[-1]]
    return X, history["date"].max()


def _rain_probability(model, X: pd.DataFrame, rain_flag: int) -> float:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        if proba.shape[1] == 2:
            return float(proba[0, 1])
    return 0.75 if rain_flag else 0.15


def _normalize_temperatures(row: dict[str, Any]) -> None:
    lo = float(row["temp_min"])
    avg = float(row["temp_avg"])
    hi = float(row["temp_max"])
    ordered_lo = min(lo, avg, hi)
    ordered_hi = max(lo, avg, hi)
    row["temp_min"] = round(ordered_lo, 1)
    row["temp_max"] = round(ordered_hi, 1)
    row["temp_avg"] = round(min(max(avg, ordered_lo), ordered_hi), 1)


def predict_next_days(
    days: int = FORECAST_DAYS,
    csv_path: str | Path = CSV_PATH,
    model_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    days = max(1, min(int(days), FORECAST_DAYS))
    out_dir = _model_dir(model_dir)
    meta_path = out_dir / "meta.json"
    if not meta_path.exists():
        raise RuntimeError("模型尚未訓練，請先執行 /api/predict/train")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    X, latest_date = _latest_features(csv_path, meta)
    forecast: list[dict[str, Any]] = []

    for horizon in range(1, days + 1):
        pred_date = latest_date.date() + timedelta(days=horizon)
        row: dict[str, Any] = {
            "day_index": horizon,
            "date": pred_date.isoformat(),
        }

        for target in REGRESSION_TARGETS:
            model = joblib.load(out_dir / f"h{horizon}_{target}.joblib")
            value = float(model.predict(X)[0])
            if target in {"rainfall_mm", "humidity_pct", "wind_speed_kmh"}:
                value = max(0.0, value)
            if target == "humidity_pct":
                value = min(100.0, value)
            row[target] = round(value, 1)

        rain_model = joblib.load(out_dir / f"h{horizon}_rain_yn.joblib")
        rain_flag = int(rain_model.predict(X)[0])
        row["rain_yn"] = rain_flag
        row["rain_prob"] = round(_rain_probability(rain_model, X, rain_flag), 3)
        if row["rain_prob"] < 0.35:
            row["rainfall_mm"] = round(min(row["rainfall_mm"], 2.0), 1)

        _normalize_temperatures(row)
        forecast.append(row)

    return forecast


def model_metrics(model_dir: str | Path | None = None) -> dict[str, Any]:
    meta_path = _model_dir(model_dir) / "meta.json"
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))
