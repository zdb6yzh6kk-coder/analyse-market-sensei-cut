from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.sort_values("date").copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["ema_20"] = frame["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    frame["ema_50"] = frame["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    frame["ema_100"] = frame["close"].ewm(span=100, adjust=False, min_periods=100).mean()
    frame["ema_200"] = frame["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    frame["return_1"] = frame["close"].pct_change(1) * 100
    frame["return_5"] = frame["close"].pct_change(5) * 100
    frame["return_20"] = frame["close"].pct_change(20) * 100
    frame["volatility_20"] = frame["close"].pct_change().rolling(20, min_periods=10).std() * np.sqrt(252) * 100
    return frame


def classify_trend(data: pd.DataFrame) -> str:
    latest = data.dropna(subset=["close"]).iloc[-1]
    close = latest["close"]
    ema_20 = latest.get("ema_20")
    ema_50 = latest.get("ema_50")

    if _valid(ema_20) and _valid(ema_50):
        if close > ema_20 and close > ema_50 and ema_20 > ema_50:
            return "bullish"
        if close < ema_20 and close < ema_50 and ema_20 < ema_50:
            return "bearish"
    return "neutral"


def latest_snapshot(data: pd.DataFrame) -> dict:
    latest = data.dropna(subset=["close"]).iloc[-1]
    return {
        "close": float(latest["close"]),
        "ema_20": _to_float(latest.get("ema_20")),
        "ema_50": _to_float(latest.get("ema_50")),
        "ema_100": _to_float(latest.get("ema_100")),
        "ema_200": _to_float(latest.get("ema_200")),
        "return_1": _to_float(latest.get("return_1")),
        "return_5": _to_float(latest.get("return_5")),
        "return_20": _to_float(latest.get("return_20")),
        "volatility_20": _to_float(latest.get("volatility_20")),
        "last_updated": str(pd.to_datetime(latest["date"]).date()),
    }


def relative_strength(data: pd.DataFrame, benchmark: pd.DataFrame) -> float:
    symbol_return = _latest_number(data, "return_20")
    benchmark_return = _latest_number(benchmark, "return_20")
    return round(symbol_return - benchmark_return, 2)


def _latest_number(data: pd.DataFrame, column: str) -> float:
    if column not in data or data.empty:
        return 0.0
    return _to_float(data[column].iloc[-1])


def _to_float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _valid(value) -> bool:
    return value is not None and not pd.isna(value)
